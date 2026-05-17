# Stage 09 — Multi-machine CPU fan-out via Cloud Run Jobs

**Status: implemented + locally validated. Cloud deployment is one `gcloud run jobs create` away.**

s09 takes s08's "ship s07 to one cloud machine" and scales it across **many machines** by submitting a Cloud Run Job with N parallel tasks. Each task computes its slice of the frame schedule and commits to a shared icechunk repo in GCS.

Compared to s11 (GKE multi-Pod GPU fan-out) this is the simpler architectural step: serverless containers, no Kubernetes control plane, pay-per-task-second, scales to zero between runs.

## Where this sits in the cloud progression

|  | CPU | GPU |
|---|---|---|
| Single | [s08](../s08_zoom_cloud_cpu/) | [s10](../s10_zoom_cloud_gpu/) — placeholder |
| Many | **s09** (this stage) | [s11](../s11_zoom_fanout_gpu/) — scaffold |

s09 adds machine count over s08; same `compute_frame` (s03's single-thread numba kernel — see `compute.py`), same canonical schedule, same image. The new piece is **how many containers run in parallel** and **how they share the output store** (icechunk's transactional commits handle concurrent writers).

## Two execution modes (auto-detected from env)

```python
# In run.py
if "CLOUD_RUN_TASK_INDEX" in os.environ:
    run_task()      # inside a Cloud Run task
else:
    run_dispatch()  # control host (laptop or CI)
```

**`task` mode** — runs inside one Cloud Run task. Reads `CLOUD_RUN_TASK_INDEX` + `CLOUD_RUN_TASK_COUNT` from env; reads run parameters from `MANDELFLOW_*` env vars set by the dispatcher. Computes its slice of the schedule (e.g., task 3 of 8 with 120 frames → frames 45..60). Writes each frame as one icechunk commit.

**`dispatch` mode** — runs locally. Initialises the icechunk repo + schema at the GCS path, then calls `gcloud run jobs execute` to spawn N parallel tasks. Waits for completion.

## Why s03 (single-thread) and not s04 (Dask)

Each Cloud Run Job task runs in its own container with 2 vCPUs by default. Adding Dask's intra-frame parallelism would launch 1-2 Dask worker processes per task — overhead doesn't pay for the small speedup. The parallelism story for s09 is **task count, not per-task threads**.

If you bump to 4-vCPU tasks (`--cpu 4`), swap `compute.py`'s import to `stages.s04_dask_local.compute` and the rest of the stage is unchanged.

## Why icechunk specifically

Multiple Cloud Run tasks write concurrently to the same Zarr store. Raw Zarr's chunk-level write semantics are "trust no two workers touch the same chunk" — which is *technically* true for our `(1, H, W)` per-frame chunks, but unsafe under any retry / restart scenario, and there's no transactional rollback if one task crashes mid-write.

icechunk's **session-based commits** handle this cleanly: each task opens a writable session, writes its frames, commits. Two sessions modifying disjoint regions (true for us — different frame indices = different chunks) merge automatically. The commit log of `main` becomes the data lineage.

For local testing icechunk on the filesystem still works, but it warns it's not safe under true concurrent commits (filesystem doesn't have the atomic primitives GCS does). The cloud path uses `icechunk.gcs_storage` which IS safe.

## One-time setup (Cloud Run Job creation)

```bash
gcloud run jobs create mandelflow-zoom \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev \
  --command python \
  --args="-m,stages.s09_zoom_fanout_cpu.run" \
  --service-account mandelflow-vm@mandelflow-2026.iam.gserviceaccount.com \
  --cpu 2 --memory 4Gi --task-timeout 1800
```

This creates the Job definition. `gcloud run jobs execute` (called by the dispatcher) overrides task count + env vars at execution time without modifying the Job itself.

The runtime service account (`mandelflow-vm`) is the same one s08 uses. It already has `roles/storage.objectAdmin` on the bucket.

## Running it

```bash
# From your laptop (the dispatcher; not inside any container)
python -m stages.s09_zoom_fanout_cpu.run \
  --n-frames 120 \
  --n-tasks 8 \
  --resolution 720 \
  --max-iter 512 \
  --output gs://mandelflow-2026-zarr/runs/s09.icechunk

# Dispatcher will:
# 1. open_or_create the icechunk repo at the output URL
# 2. init the dataset schema (idempotent)
# 3. submit `gcloud run jobs execute mandelflow-zoom --tasks 8 --parallelism 8 ...`
# 4. wait for completion
```

Each task computes ~15 frames sequentially; 8 tasks run in parallel. Expected wall-clock ~30-60s including cold-start (Cloud Run cold starts add ~10-20s per task).

Cost: ~$0.002 per run. Cloud Run Jobs is dirt cheap for this workload.

## Tear down

The Cloud Run Job itself costs nothing while idle (no standing tasks). To delete:

```bash
gcloud run jobs delete mandelflow-zoom --region us-central1
```

The icechunk repo persists in GCS until you `gsutil -m rm -r gs://.../runs/s09.icechunk` or `terraform destroy` (force_destroy=true on the bucket).

## Local validation (no cloud)

The task code is runnable locally by setting the env vars Cloud Run would set:

```bash
for task in 0 1 2 3; do
  CLOUD_RUN_TASK_INDEX=$task CLOUD_RUN_TASK_COUNT=4 \
  MANDELFLOW_N_FRAMES=20 MANDELFLOW_OUTPUT=out/s09_test.icechunk \
  MANDELFLOW_RESOLUTION=240 MANDELFLOW_MAX_ITER=256 \
  uv run python -m stages.s09_zoom_fanout_cpu.run
done
```

Each iteration of this loop simulates one Cloud Run task. Sequentially they fill in the icechunk repo with all 20 frames (validated 2026-05-17 — 22 commits total in main, 20 frame commits + schema init + repo init).

## Known follow-ups

- **Terraform for the Cloud Run Job.** Currently the Job is created via `gcloud` (one command). For reproducibility this should land in `stages/s09_zoom_fanout_cpu/terraform/` as a `google_cloud_run_v2_job` resource.
- **Image rebuild needed before first cloud run.** The current Artifact Registry image (`compute:dev`) was built before s09's code existed. Rebuild via `gcloud builds submit --config cloudbuild.yaml --region us-central1 .` (~2 min with the registry cache from `cloudbuild.yaml`).
- **The dispatcher uses `subprocess.run("gcloud", ...)`.** That assumes the dispatcher host has gcloud installed + authenticated. A pure-Python path via the Cloud Run v2 SDK (`google-cloud-run`) would remove that dependency; we use the subprocess form because the SDK adds 10MB of deps and adds nothing for our use case.
