# Weekend build plan

Chronological implementation order. Designed so each milestone produces something demonstrable. The pedagogical structure (stages 00–09) is independent of this build order — Saturday gets the laptop spine working; Sunday adds cloud + viewer.

## Prerequisites

Land these before kicking off Saturday:

- `pyproject.toml` + `uv.lock` committed; `uv sync` resolves cleanly on the laptop. (~30 min)
- Repo-root `Dockerfile` + `.dockerignore`; `docker build .` succeeds (perf testing only happens on a GPU node, but the build must complete locally). (~30 min)
- GCP project provisioned with billing enabled, and a separate Workload Identity Federation pool reserved for GitHub Actions OIDC. Budget ~1 hr — the WIF setup is its own dance, see GOTCHAS #6.

## Saturday — laptop foundations (~8 hrs)

**Goal by EOD:** Dagster materialising the `iterations` and `animation_mp4` assets locally, end-to-end. Stages 00–04 and 07 functional. A real zoom MP4 rendered from a real Zarr.

| Block | Time | Deliverable |
|---|---|---|
| `common/` skeleton | 1h | `schedule.py` (canonical zoom path, `frame_i → (center, width)`), `store.py` (xarray + Zarr schema, open/create helpers), `colormap.py` (shared palette). Commit dtype (`uint16`) and chunk strategy (`(1, H, W)`) here. |
| Stage 00 (naive) + 01 (numpy) | 1h | Both implement `compute_frame(...)` and a `run.py` CLI. Both write a `(1, H, W)` Zarr at small scales. Reference output for tests. |
| Stage 02 (numba) + 03 (numba-opt) | 1h | Numba `@jit` over the per-pixel iteration, then `@vectorize(target="parallel")` with `fastmath=True` and cardioid / period-2 / periodicity early-exits. Add tests asserting their Zarrs match stage 00's within tolerance. |
| `render/frame.py` + `animation.py` | 1h | Read a Zarr → PNG / MP4 via `ffmpeg` subprocess. Pure functions; called by Dagster asset *and* by stage `run.py` for standalone use. |
| Dagster orchestration | 2h | `iterations` asset partitioned by frame; `frame_pngs` and `animation_mp4` downstream. `LocalZarrIOManager`. `dagster dev -m orchestration.definitions` shows the asset graph and materialises. |
| Stage 04 (dask-local) | 1h | Same asset, Dask backend for one big single-frame render. Fans tiles across cores locally. |
| Stage 07 (zoom-local) | 1h | Unlock the frame dimension. Multi-frame zoom on one machine using s06's kernel with a shared GL context. End-of-day deliverable: a real zoom animation rendered from a real multi-frame Zarr. |

## Sunday — cloud + viewer (~9 hrs)

**Goal by EOD:** Stage 08 (CPU single VM) running on a single GCE VM with output in `gs://bucket/run.zarr`. Stage 11 (optional) materialising the asset against a GKE cluster with GPU Pods. Stage 12 tile server live on Cloud Run serving frames + slippy-map tiles from a precomputed pyramid. CI green. Repo demoable.

| Block | Time | Deliverable |
|---|---|---|
| Stage 05 (gpu-torch) | 1h | Single-frame GPU rendering via PyTorch MPS / CUDA. Test on local GPU if available; CI import-tests only. |
| Stage 06 (gpu-shader) — headless EGL | 2h | Hardest single block of the weekend. Validate the repo-root Dockerfile against ModernGL + EGL on a real GPU node (one-off GCE GPU VM if your Mac isn't enough). First successful headless render inside the container is the milestone. |
| Stage 08 (zoom-cloud, CPU) — Terraform + first run | 1.5h | `terraform apply` provisions: one GCE VM (CPU), GCS bucket, attached service account, Artifact Registry. SSH onto the VM, run the container, write `gs://bucket/run.zarr`. Simplest cloud deployment. |
| Stage 11 (zoom-fanout-gpu) — Terraform GKE | 2h | One `terraform apply` provisions: GKE Standard cluster, GPU node pool (`n1-standard-4` + T4), Workload Identity Federation pool for GitHub OIDC. Outputs paste into GitHub Secrets. |
| Stage 11 — Dagster K8s executor + GCS IOManager | 1.5h | Swap the executor config; swap `LocalZarrIOManager` → `GCSZarrIOManager`. Materialise the `iterations` asset against the K8s executor; chunks land in `gs://bucket/run.zarr`. *Same asset code as Saturday.* |
| Stage 12 (viewer-fastapi tile server) | 1.5h | Read-only: `/runs`, `/runs/{id}/frame/{i}.png`, `/tiles/{run_id}/{z}/{x}/{y}.png`. Pure CPU — no GPU, no GL context. Local-first; deploy to Cloud Run (scales to zero). |
| GitHub Actions | 1h | `pr.yml` (lint, pytest stages 00–04, terraform validate, dagster definitions check). `deploy.yml` (Workload Identity auth → build → push → deploy viewer to Cloud Run). |
| README pass + LinkedIn post | 30 min | Embed bench charts, link to viewer URL + MP4, post draft. |
| **Tear down** | 15 min | `terraform destroy`. Phone alarm. GPU nodes burn money. |

## Cost (revised for Dagster + Cloud Run viewer)

- **GPU node** (`n1-standard-4` + T4): ~$0.40/hr. Weekend usage ~10 hrs ≈ **$4**.
- **CPU nodes** (Dagster control plane + non-GPU partitions): ~$0.15/hr ≈ **$2**.
- **Cloud Run** (viewer read endpoints): pennies (scales to zero between requests).
- **GCS** (Zarrs at ~1 GB each): pennies.
- **Artifact Registry, networking**: pennies.

**Total: ~$8–10** if you tear down the GPU pool promptly. Pre-load $30 of GCP credit for 3x headroom.

## What's intentionally out of scope

- **Real-time multi-user pan/zoom with WebSockets.** A serious interactive UI is a project of its own; stage 09's tile server returns precomputed tiles, not live streams.
- **An ML model.** Adding a classifier dilutes the focus. The Mandelbrot pipeline is already rich enough.
- **Prometheus + Grafana observability.** Worthwhile stretch goal if Sunday finishes early. Not core.
- **Deep zoom past 10¹².** Perturbation theory + double-float emulation is its own substantial body of work; stage 06's shader targets up to ~10¹² and that's the scope here.
