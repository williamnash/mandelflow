# Next steps

Backlog of issues + improvements identified during the first successful
cloud fan-out (portfolio preset, 600 frames, 4-Pod GKE Indexed Job,
2026-05-18). Each item is sized to become a single GitHub issue.

Priorities:

  - **P0** correctness — wrong output, data loss, silent failure
  - **P1** quick win or blocker for the next planned milestone (showcase
    preset, GPU path)
  - **P2** quality-of-life or longer-term optimisation

---

## P0 — correctness

### 1. icechunk coord-array conflicts drop 2 of 4 Pods' metadata

**Discovered:** portfolio-003 run on 2026-05-18.

**Problem.** After a successful 4-Pod dispatch, the resulting icechunk
repo has correct `iterations` data for all 600 frames, but the `width` /
`center_re` / `center_im` coord arrays are NaN for 300 of 600 frames
(Pod 0's range 0–149 and Pod 2's range 300–449). The alternating pattern
strongly suggests `icechunk.BasicConflictSolver` resolves coord-array
conflicts as all-or-nothing — when a session rebases, the solver keeps
*one* version of the full coord array, discarding the other.

`iterations` survives cleanly because each Pod writes via region-write
(`region={"frame": slice(k, k+1)}`) — different Pods touch different
chunks. Coords are full-length arrays where every Pod's session
"modifies the whole array" (most entries are NaN placeholders) and
that's the conflict the solver mishandles.

**Fix.** The dispatcher already knows all coords up-front (they're
deterministic from `canonical_schedule(n_frames, initial_width,
final_width)`). Compute them once, populate during `_init_schema`,
and have Pods only write the disjoint `iterations` chunks. No coord
writes inside the per-Pod commit. Eliminates the conflict by
construction.

**Effort.** ~30 min in `stages/s09_zoom_fanout_cpu/run.py`. Schema
init changes from placeholder NaN coords to fully-populated coords;
`run_task` drops the `center_re`/`center_im`/`width` from the per-frame
`ds_frame` and writes only `iterations`.

**Verify.** Re-run portfolio at n_pods=4, check `ds.width.values` —
should have no NaN.

---

## P1 — quick wins / showcase blockers

### 2. ✅ DONE — Linear contiguous sharding is unbalanced for deep-zoom workloads

> Implemented as `common/config.py::frame_indices_for_pod` (stride
> sharding), wired into `run_task` and the Dagster `iterations` asset;
> unit-tested in `tests/unit/common/test_config.py`. **Validated on GKE
> 2026-06-11** (`bench/results/s09_portfolio_stride.json`): same
> portfolio workload, 4 pods — makespan 8m33s vs this baseline's 21min
> (**2.46×**), per-task compute max/mean **1.30×** vs 17×. Original
> writeup kept below for the record.

**Discovered:** portfolio-003 wall-clock was 21 min total. Pod 0 finished
in 58 s; Pod 3 took ~17 min. **17× imbalance.**

**Problem.** The current sharding rule assigns frame `[i × n/k, (i+1) ×
n/k)` to Pod `i`. For a zoom schedule, frames near the end have more
interior pixels (deeper near the boundary of M) and run several times
slower per frame than outer frames. Pod 3 (deepest 25%) does roughly the
same total *work* as Pods 0+1+2 combined, but linearly in sequence
inside one Pod. Wall-clock is bounded by Pod 3.

**Fix.** Stride-sharding: Pod `i` gets frames `i, i+k, i+2k, …`. Each
Pod gets a mix of shallow + deep, total work is even. For 4 Pods on 600
frames, every Pod gets every-4th-frame. Expected speedup vs status quo:
~3× wall-clock reduction for the same workload.

Trade-off — the icechunk commit message gets less neat ("task 3: frames
3, 7, 11, …, 599" instead of "frames 0450..0599"). The `iterations`
region writes still hit disjoint chunks, so the architecture stays
correct.

**Effort.** ~20 min — modify `common/config.py::frame_range_for_pod` (or
add a sibling `frame_indices_for_pod`) + update `run_task` and the
Dagster asset to use the new shape.

### 3. ✅ DONE — Pre-populating coords at schema init (companion to #1)

> Implemented: `_init_schema` now takes the `RunConfig` and writes all
> coords from the canonical schedule; task region-writes carry only the
> iterations variable. The race was confirmed in production first —
> portfolio-stride-002 landed 600/600 iteration frames but only 150/600
> coords (each 1-D coord array is one chunk; every task's commit carried
> a full copy, NaN outside its own frames, and the rebase kept the last
> one). Pinned by `tests/integration/test_s09_coords.py`. Original
> writeup kept below.

**Same fix as #1.** Listing separately because the *coord-populated*
schema init is also what makes the data scientifically clean — every
frame's `width` is queryable for downstream filtering, e.g.
`ds.sel(width=slice(1e-4, 1e-6))` to render only the mid-zoom portion.

### 4. Request a zonal CPU quota increase

**Discovered:** first dispatch attempt with n_pods=8 hit `FailedScaleUp:
GCE quota exceeded in zone us-central1-a` even though regional CPU quota
was 4096 / 8 used.

**Problem.** New GCP projects have a per-zone CPU quota that's much
smaller than the regional one (~24 vCPU per zone is typical). At 2 vCPU
per e2-standard-2, we hit it at 4 Pods per zone. Spread across 2 zones
that's 8 Pods total — enough for portfolio, not enough for showcase at
n_pods=8 unless the autoscaler successfully splits across 3 zones (which
worked once tonight but isn't reliable).

**Fix.** GCP Console → IAM & Admin → Quotas → search "CPUs" → filter
location = `us-central1-a` / `-b` / `-c`. Request increase to 32 vCPU
per zone (3× current). Approval is typically same-day.

**Effort.** 5 min to submit; 4–24 h to approve. Do this before the
showcase run.

### 5. backoffLimit > 0 in the Job template

**Discovered:** twice tonight (quota failure, then icechunk conflict
before the fix) a single Pod's failure killed the entire 4-Pod Job and
deleted Pods that had already done minutes of work.

**Problem.** `backoffLimit: 0` is too strict for batch workloads where
recoverable Pod failures are normal — autoscaler timing, transient API
errors, etc. The current setting trades cheap-blast-radius diagnostics
(any failure stops the world) for lost work.

**Fix.** Bump to `backoffLimit: 2` in
`stages/s09_zoom_fanout_cpu/k8s/job.yaml.tmpl`. K8s will retry a failed
Pod up to 2 times; if a Pod fails permanently after 3 attempts, that's
real and we want to know. With the conflict-retry logic in `run.py`,
most real failures will surface in Pod logs anyway.

**Effort.** 1-line edit. Validate by intentionally failing a Pod (e.g.,
remove a required env var) and confirming the others complete.

### 6. Image size / Pod startup: split CPU and GPU images

**Discovered:** image is **4.6 GB**, per-Pod cold image pull is ~1m44s,
showcase Pod startup waves will be the wall-clock bottleneck.

**Problem.** Current `Dockerfile` builds one image with CUDA 12 runtime
+ Mesa EGL + the full Python venv. CPU-only Pods (s09 numba kernel) pull
~3 GB of CUDA libs they never load. With image streaming disabled, every
new node pays the full pull.

**Fix options** (pick one):

  - **A. Two Dockerfile variants.** `Dockerfile.cpu` (slim Python base)
    + `Dockerfile.gpu` (current CUDA + Mesa). Cloud Build emits
    `compute-cpu:dev` and `compute-gpu:dev`. The dispatcher picks the
    right tag per `--target`. Breaks the one-Dockerfile invariant in
    CLAUDE.md, but the invariant exists for ergonomic reasons not
    architectural ones.

  - **B. Build args on one Dockerfile.** `BUILD_VARIANT=cpu|gpu` arg
    selects the base image and skips CUDA-dependent layers. Keeps one
    Dockerfile. Slightly more complex Dockerfile logic.

  - **C. Enable GKE Image Streaming.** Cluster-level config change:
    streams only the file system blocks the container actually reads;
    Pod starts running while the rest streams in the background.
    Doesn't reduce image size on disk, but cold-pull drops from ~90s
    to ~5–10s.

C is the simplest test of "does this help?" and reversible. A or B are
the right architectural answer.

**Effort.** C: ~5 min terraform change + re-apply on the node pool.
A or B: 1–2 hours including a Cloud Build update for the new tags.

---

## P1 — for the architecture pivot we already made

### 7. Cloud Build provenance/SBOM disabled — verify it lands

**Done in code.** `cloudbuild.yaml` updated with `--provenance=false`
and `--sbom=false`. Effect won't be visible until the next build.

**Verify.** Next time we rebuild the image, check Cloud Build duration —
expect ~3 min for cache-warm, vs the 6 min we saw tonight.

### 8. Test showcase preset on GKE end-to-end

**Pending.** Showcase = 1800 frames × 2160² × 8192 iter. Expected
~20 min wall-clock with proper sharding (issue #2), longer without.
Should run after issues #1, #2, #5 are addressed; otherwise wastes the
$0.30 of cluster time.

**Effort.** ~30 min including bringing up the cluster (it's destroyed
between sessions).

---

## P2 — performance / quality-of-life

### 9. Machine-type investigation: e2 vs n2 vs c2

**Half-investigated tonight.** Initial hypothesis was e2 burst-credit
exhaustion. `kubectl top` revealed Pod 3 was using ~1 vCPU at 54% node
load (not throttled). So the burst-credit story doesn't apply.

**But:** e2 is described by GCP as "general-purpose / spiky workloads,"
where n2/c2 are described as "sustained CPU performance." On a budget
the e2 win is real ($0.07/hr vs $0.10/hr n2), but n2 may give more
predictable wall-clock for batch.

**Action.** Run the same portfolio dispatch on n2-standard-2 and
c2-standard-4 node pools, compare per-frame timing variance. If n2 is
within 20% cost for >2× more predictable timing, switch.

**Effort.** ~1 hour of measurement + terraform variant.

### 10. Render pipeline: parallelise the ffmpeg encode

**Future-facing.** Current `render/animation.py` is single-process,
single-ffmpeg. At 4K showcase scale (1800 × 2160²) the encode would
take ~10 min.

**Fix.** Render in N segments (e.g., 4 chunks of 450 frames each), run
4 ffmpegs in parallel writing 4 partial MP4s, then `concat` filter to
join. Or use libx265 with `--frame-threads` (helps but limited).

**Effort.** ~2 hours including correctness testing for segment
boundaries.

### 11. The Dagster k8s_job_executor path is unused

**Existing architecture.** `orchestration/definitions.py` supports
`MANDELFLOW_EXECUTOR=k8s_cpu/k8s_gpu` against a Dagster instance. We
pivoted to raw K8s Indexed Jobs tonight because driving the executor
from a laptop CLI needs a `dagster-daemon` daemon.

**Future.** When/if a Dagster server is deployed (on GKE itself), the
executor path becomes useful — gives the asset-graph UI, lineage,
retries, etc. Until then, leave the code in `definitions.py` as
"future option" with a comment to that effect.

**Effort.** 0 (just a doc note); ~half a day to actually deploy a
Dagster server if we want it.

### 12. Re-evaluate the pod-startup time after the fix

**After issue #6.** Once we have either GKE Image Streaming or a slim
CPU image, re-measure cold Pod startup. Expectation: drops from ~1m44s
to ~10–20 s. That alone would have made tonight's portfolio run finish
in ~3 min wall-clock instead of 21.

### 13. Audit script enhancement: cluster-cost breakdown

**Existing.** `scripts/audit_cloud.sh` lists what's running. Doesn't
surface a "current burn rate" estimate.

**Enhancement.** Add a final section that sums known per-hour costs
(control plane + node count × per-node rate + ...) into a single
$/hour and $/day projection. Useful for "is it safe to walk away."

**Effort.** ~30 min.

---

## How to use this list

When picking what to do next:

1. P0 first. Issue #1 is the only correctness bug; the data we produce
   tonight is *almost* right but the metadata is wrong. Fix before
   showcase.
2. P1 in this order: #2 (stride-sharding) > #4 (quota) > #5
   (backoffLimit) > #6 (image size). Each unlocks the next.
3. Don't pre-optimise the P2 items — only do them when a measurement
   says they're needed for the workload you actually want to run.

Filed-as-issues version (one-liners) appears at the bottom of
`docs/RUNBOOK.md` once tonight's GitHub-issue-creation pass happens.
