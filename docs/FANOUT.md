# Fan-out architecture

How `mandelflow` distributes a multi-frame Mandelbrot zoom across N workers
writing to one shared store. This doc is the deep-dive that goes with the
code in `orchestration/definitions.py`, `common/config.py`, and
`stages/s09_zoom_fanout_cpu/terraform/`. The pattern generalises to any
embarrassingly-parallel batch workload — the Mandelbrot is just the
vehicle.

## 0. The problem

We have N frames of work, each independent. We want to run them across
K machines so total wall-clock is roughly `(N/K × per_frame_time) +
(machine startup × parallel waves)`. The interesting question is what
*shape* of work to assign each machine — and that question is more subtle
than it looks.

The naive answer ("one frame per machine") is wrong for our workload.
Most of this doc explains why, and what the right shape is.

## 1. The pod-startup problem

Spinning up a Pod on GKE is not free. The wall-clock budget for a Pod
that does any work at all:

```
Pod schedule on node    ~2–5 s     (kubelet, networking)
Image pull (cached)     ~1–3 s     (manifest fetch, layer hardlink)
Container start         ~0.5 s     (containerd/runc)
Python interpreter      ~2–4 s     (`uv run` import path)
App imports             ~5–10 s    (numpy, xarray, icechunk, dagster)
Repo / GL context open  ~1–5 s     (icechunk session, EGL context)
─────────────────────────────────
Total before any work   ~15–30 s
```

Call this **S** (startup). It is a fixed cost per Pod per run.

Now suppose each frame's compute takes time **F**. The total wall-clock
to compute N frames spread across K Pods running in parallel is:

```
T  =  S  +  (N / K) × F                                (single wave)
T  =  S × (N / (K × frames_per_pod))  +  N/K × F        (multiple waves)
```

The ratio that matters for fan-out efficiency is **(frames_per_pod × F)
/ S** — the compute-to-startup ratio. If this is ≪ 1, your Pods are
mostly burning their lifespan importing Python. If it's ≥ 1, you're
actually doing useful work in parallel.

### Where the wrong answer hides

The seductive answer is "one frame per Pod" — partition the work the same
way you describe the data ("our data is partitioned by frame, so the
asset should be partitioned by frame"). It feels natural. It maps cleanly
to retry semantics ("frame 0042 failed, just rerun frame 0042"). The
Dagster asset graph UI gives you a beautiful tile per frame.

But for our workload at 1080² and `max_iter=1024`:

```
S = 25 s
F = 70 ms (numba single-thread per frame)

Compute-to-startup ratio = F / S = 0.003 = 0.3%
```

For every second of useful work, we'd be paying **300 seconds of Pod
startup**. The GPU case is worse: F ≈ 10 ms, ratio = 0.04%. We'd burn
~$0.40/hr on a T4 to keep it idle 99.96 % of the time.

This is the lesson behind `stages/s11_zoom_fanout_gpu/README.md`'s warning:

> Per-Pod startup overhead is ~15–50s; per-frame compute is ~5–10ms on
> a T4. That ratio is ~5,000:1 — startup would dominate everything.

### The right shape: frame-range-per-Pod

Instead of partitioning by frame, partition by **Pod**. Each partition
is "Pod *i* of *K*", and each Pod's asset code internally loops over
its contiguous frame range:

```python
@asset(partitions_def=pod_partitions, ...)
def iterations(context):
    pod_idx = int(context.partition_key)
    start, end = _frame_range_for_pod(pod_idx)   # e.g. pod 3 of 8: [225..300)
    out = {}
    for k in range(start, end):
        out[k] = compute_frame(cr[k], ci[k], w[k], ...)
    return out   # dict[frame_idx → ndarray]
```

A Pod now does many frames in one lifetime. Concretely for our targets
(see `common/config.py`); per-frame numbers are *measured* for portfolio
(numba single-thread on Apple Silicon) and extrapolated linearly for the
others (CPU compute is linear in pixel count × max_iter):

| Preset | n_frames | n_pods | per-pod frames | per-pod compute (numba) | compute / startup |
|---|---|---|---|---|---|
| demo (720² / 1024 iter) | 120 | 4 | 30 | 30 × 30 ms = 0.9 s | 0.04 (bad — local only) |
| portfolio (1080² / 2048 iter) | 600 | 8 | 75 | 75 × 320 ms = **24 s** *(measured)* | 1.0 (break-even) |
| showcase (2160² / 8192 iter) | 1800 | 8 | 225 | 225 × 5.1 s = **~19 min** | 46 (excellent) |

The "showcase" preset is what actually justifies cloud fan-out. With
8 Pods in parallel, wall-clock is ~19 min plus 25 s startup ≈ ~20 min
total — instead of 8 × 19 min ≈ 2.5 hours single-threaded.

### Side benefit: shared kernel state

A Pod that does 30 frames in sequence can create its GL context, JIT
its compute kernel, open its icechunk session **once** and reuse those
across all 30 frames. With per-frame Pods you pay every initialisation
30 times. The shared-state win is on top of the startup-amortisation win.

## 2. Dagster's pieces, mapped

Dagster has its own vocabulary. Here's how each piece carries our
architecture:

```
   ┌─────────────────────────────────────────────────────────────────┐
   │  ASSET                                                          │
   │    iterations  (the data product, declaratively defined)        │
   │    │                                                            │
   │    ├─ partitions_def: pod_partitions (StaticPartitionsDef)      │
   │    │     keys: "0000", "0001", ..., "000N"                      │
   │    │                                                            │
   │    └─ io_manager_key: "zarr_io" (which IOManager writes output) │
   └─────────────────────────────────────────────────────────────────┘
                              ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  STEP (created per partition during materialisation)            │
   │    one step = one Pod = one partition's work                    │
   │                                                                 │
   │    runs the asset's function body                               │
   │    output is passed to the IOManager via handle_output()        │
   └─────────────────────────────────────────────────────────────────┘
                              ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  EXECUTOR (how Steps run)                                       │
   │    multiprocess_executor: spawns OS processes locally           │
   │    k8s_job_executor:      submits one K8s Job per step          │
   │    in_process_executor:   runs serially in one process          │
   └─────────────────────────────────────────────────────────────────┘
                              ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  IOMANAGER (what to do with the Step's output)                  │
   │    ZarrFrameIOManager:     writes to raw Zarr (single writer)   │
   │    IcechunkFrameIOManager: opens session, writes frames,        │
   │                            commits once per Pod                 │
   └─────────────────────────────────────────────────────────────────┘
```

**The architectural payoff:** the asset code is identical no matter
which executor or IOManager is wired up. Local laptop with
`multiprocess + zarr` and a GKE cluster with `k8s_cpu + icechunk` run
the *same* `compute_frame` calls in the asset body. The only thing
that changes is plumbing.

In `orchestration/definitions.py` this is selectable via three env vars:

```bash
MANDELFLOW_EXECUTOR=multiprocess|k8s_cpu|k8s_gpu
MANDELFLOW_STORAGE=zarr|icechunk
MANDELFLOW_KERNEL=numba_cpu|dask_cpu|gpu_shader
```

Plus the workload-shape via `MANDELFLOW_PRESET=demo|portfolio|showcase`
or individual `MANDELFLOW_N_FRAMES`, `_RESOLUTION`, `_N_PODS` overrides.

## 3. RunConfig and presets

Module-level constants make config edits a code change. Env-driven
configs make them a deployment change. We want the latter:

```python
# common/config.py
@dataclass(frozen=True)
class RunConfig:
    n_frames: int = 120
    resolution: int = 720
    initial_width: float = INITIAL_WIDTH
    final_width: float = FINAL_WIDTH
    fps: int = 30
    n_pods: int = 4
    max_iter: int = 1024

PRESETS = {"demo": ..., "portfolio": ..., "showcase": ...}

def from_env(default_preset="demo") -> RunConfig:
    cfg = PRESETS[os.environ.get("MANDELFLOW_PRESET", default_preset)]
    # Apply any MANDELFLOW_* overrides
    return replace(cfg, **resolve_env_overrides())
```

The k8s_job_executor in `definitions.py` forwards every `MANDELFLOW_*`
env var into spawned Pods, so a Pod re-loads `from_env()` and gets the
same config the dispatcher had. *Same code, same config, different
machine.*

### Why no `max_iter` schedule

An earlier draft had `max_iter_schedule()` — outer frames at low iter
(cheap), deep frames at high iter (rendering quality). It looked clever.

It wasn't worth it. Mandelbrot has several early-exit shortcuts:

- **Escape on radius.** As soon as |z| > 2, the point escapes. Most
  pixels in outer frames escape in <50 iterations.
- **Cardioid / period-2 bulb test.** Points provably in M can be
  identified by closed-form predicates before any iteration. Two extra
  multiplies per pixel save up to `max_iter` worth of work.

Together these mean a high `max_iter` on outer frames is nearly free —
the pixels that *would* be expensive (deep interior) don't exist out
there. Setting `max_iter = 8192` for all frames at the showcase preset
costs ~5 % more compute than depth-scheduling and saves a whole field
+ helper function. YAGNI'd it. See the corresponding gotcha in
`docs/GOTCHAS.md`.

## 4. The icechunk side: one commit per Pod

`IcechunkFrameIOManager.handle_output` does this, per Pod:

```python
repo = self._open_repo()
session = repo.writable_session("main")
for k in sorted(obj):                            # obj: dict[int, ndarray]
    ds_frame = xr.Dataset(...)
    ds_frame.to_zarr(session.store, region={"frame": slice(k, k+1)})
session.commit(f"pod {context.partition_key}: frames {first}..{last}")
```

**One commit per Pod**, not one commit per frame. The commit message
names the frame range so the icechunk log reads like the Dagster log:

```
9B2ZJBS4  pod 0003: frames 0090..0119
2A4TN88S  pod 0002: frames 0060..0089
PS064HQA  pod 0001: frames 0030..0059
F17SMMYG  pod 0000: frames 0000..0029
46YKFE9J  initialize iterations dataset schema
1CECHNKR  Repository initialized
```

Both axes carry the same parallel structure: each Pod-commit lines up
1:1 with a Dagster partition-materialisation event. **Two systems of
record agreeing about who did what when**. This is the architectural
payoff DESIGN.md §7 promised.

### The race nobody mentions

`icechunk.Repository.open_or_create` is **not** safe to race across
processes. If two Pods both see "repo doesn't exist" and both call
`open_or_create`, you get two repos and one wins arbitrarily.

We get away with it locally because:
- The schema-init guard (`_ensure_schema`) checks before initialising
- Local FS Pods don't truly run concurrently when invoked one-at-a-time
  via the CLI loop
- icechunk emits a `WARN` about it which the user sees and corrects

For real cloud fan-out the pre-init is the user's responsibility:

```python
# tiny utility to run once before kicking off the fan-out
from orchestration.definitions import IcechunkFrameIOManager, CFG
iom = IcechunkFrameIOManager(path=GCS_PATH, n_frames=CFG.n_frames,
                              resolution=CFG.resolution)
iom._ensure_schema(iom._open_repo())   # idempotent — no-ops if already initialised
```

This pattern is already in `stages/s09_zoom_fanout_cpu/run.py` (the
Cloud Run dispatcher does the same dance before submitting tasks).

## 5. Cluster sizing — the n_pods relationship

The compute-to-startup ratio analysis assumes Pods can actually run in
parallel. They can't if the cluster has nowhere to put them.

GKE's scheduling rules:
- Each Pod requests CPU + memory in `resources.requests`.
- The scheduler places Pods on nodes that have enough remaining
  unrequested capacity.
- If no node fits, GKE's cluster autoscaler can add a node — *if* the
  node pool has autoscaling enabled and headroom.

Our default fan-out Pod requests:

```yaml
resources:
  requests: { cpu: 1, memory: 2Gi }
  limits:   { cpu: 2, memory: 4Gi }
```

On `e2-standard-2` (2 vCPU / 8 GiB total), one node fits roughly one
fan-out Pod plus system overhead. So **we need at least `n_pods` nodes**
to run all Pods in parallel.

That's why `stages/s09_zoom_fanout_cpu/terraform/gke.tf` has:

```hcl
resource "google_container_node_pool" "cpu_pool" {
  autoscaling {
    min_node_count = var.cpu_min_nodes   # 1  (cheap idle)
    max_node_count = var.cpu_max_nodes   # 8  (≥ n_pods)
  }
  ...
}
```

`min=1` keeps a single node around for system Pods between runs.
`max=8` matches the default `n_pods=8` — during a fan-out, autoscaler
brings nodes up; when Pods finish, it scales them back down to 1.

If you bump `MANDELFLOW_N_PODS` to 16, also bump `cpu_max_nodes` to 16
and `terraform apply`. The relationship is **strict**: under-sizing
the node pool serialises your fan-out without any error.

### Cost intuition

- Idle: 1 × e2-standard-2 + zonal control plane ≈ $0.17/hr ≈ $4/day.
- Active (8 nodes, autoscaled): ~$0.66/hr. A 13-min showcase costs
  ~$0.15.
- Autoscaler scale-down: typically 10 min after Pods drain. So a 13-min
  run actually bills ~25 min of fan-out capacity. Round costs up
  accordingly.

## 6. Validating without paying for a cluster

`multiprocess_executor` runs Pods as OS processes. Same asset code,
same IOManager, same RunConfig — just no Kubernetes. We validate the
plumbing here before pointing it at GKE:

```bash
# Pre-init the icechunk repo once (avoids the open_or_create race)
rm -rf out/dagster_run.icechunk

# Materialise one partition at a time (CLI partition-range needs
# BackfillPolicy.single_run or a Dagster daemon)
for i in 0000 0001 0002 0003; do
  MANDELFLOW_PRESET=demo MANDELFLOW_KERNEL=numba_cpu \
  MANDELFLOW_STORAGE=icechunk \
  MANDELFLOW_ICECHUNK_PATH=out/dagster_run.icechunk \
  uv run dagster asset materialize \
    --module-name orchestration.definitions \
    --select iterations --partition $i
done
```

After this you should see N+2 commits on `main`: 1 init + 1 schema +
N Pod-commits. Every frame populated. Total wall-clock ≈ N × per-pod
compute (serial because we looped, not because the asset is serial).

To exercise the *actual* fan-out parallelism — multiple Pods running
at once — use one of:

- `dagster dev` and launch a backfill via the UI (heaviest).
- A small Python wrapper around `dagster.materialize()` that submits
  partitions in parallel (lightweight, scriptable). Not yet in the repo.
- The s09 Cloud Run dispatcher (`stages/s09_zoom_fanout_cpu/run.py`,
  `--mode dispatch`), which fans out via Cloud Run Jobs instead of
  Dagster's executor.

For cloud (real K8s fan-out), the Dagster invocation needs either a
running Dagster instance (webserver + daemon) or a Python wrapper that
launches a single Dagster run whose `k8s_job_executor` spawns the Pods.
This is its own piece of work — see GOTCHAS.md #15.

## 7. What the future looks like

The asset-code shape is now portable across:

- **laptop multiprocess** — current default, validated.
- **GKE CPU fan-out (s09 Path B)** — terraform exists; Dagster
  invocation needs the wrapper or daemon described above.
- **GKE GPU fan-out (s11)** — same cluster with `gpu_node_count > 0`,
  `MANDELFLOW_EXECUTOR=k8s_gpu`. Adds a toleration + GPU resource limit
  in the Pod spec. The asset doesn't know.
- **Local kind cluster** (`stages/s11_zoom_fanout_gpu/dev/kind-cluster.yaml`)
  for plumbing tests without paying GKE.

The IOManager axis is similarly portable:

- **Raw Zarr** — single-writer, no transactions, fastest. Use for
  local single-threaded.
- **Icechunk on local FS** — transactional, but the `WARN`
  about concurrent commits means trust-but-verify.
- **Icechunk on GCS** — what s09/s11 use in production. GCS's atomic
  object writes make icechunk's commit semantics genuinely safe.

The Kernel axis (CPU numba / GPU shader) is independent of all of the
above — same fan-out pattern works for either.

## 8. Why this matters beyond Mandelbrot

The pattern generalises to **any embarrassingly-parallel batch
workload with non-trivial per-worker startup cost**:

- Photo/video processing pipelines (ffmpeg per shot, but Python imports
  matter).
- Genomic alignment (BWA per read batch).
- LLM batch inference (model load is the per-Pod startup; batch the
  prompts).
- ETL jobs over time-partitioned data.

The key questions to ask for any such workload:

1. **What's S (per-worker startup)?** Includes everything before the
   first useful op — image pull, library imports, model load, DB
   connection pool warmup, GPU init.
2. **What's F (per-unit compute)?** Single unit of the natural work
   item (frame, image, read, prompt, partition).
3. **What's the right batch size?** F × batch ≈ S × (2 to 10) for a
   reasonable compute-to-startup ratio. Don't aim for 1.0 — Pod
   failures cost you a whole batch, so leave headroom.
4. **Do workers share kernel state?** If so, batching also wins on
   shared init (GL context, JIT cache, model in GPU memory).
5. **Does the storage substrate handle concurrent writers?** If not,
   coordinate the commit semantics outside (one writer per batch,
   committing once).

`mandelflow` is one concrete instance of this pattern. The structural
move — partition by worker, not by data — is the underlying lesson.

## See also

- `orchestration/definitions.py` — the asset + IOManager + executor
  selection code.
- `common/config.py` — RunConfig and presets.
- `stages/s09_zoom_fanout_cpu/terraform/gke.tf` — cluster + node pool.
- `stages/s09_zoom_fanout_cpu/README.md` — Cloud Run vs GKE deployment
  paths.
- `stages/s11_zoom_fanout_gpu/README.md` — GPU fan-out delta over s09.
- `docs/DESIGN.md` — the broader architecture this fits inside.
- `docs/GOTCHAS.md` — sharp edges, including the ones unique to this
  fan-out shape.
