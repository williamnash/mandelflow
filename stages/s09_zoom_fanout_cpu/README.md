# Stage 09 — Multi-machine fan-out, CPU kernel

**Status: placeholder.** Named but not implemented.

## What this stage would be

s09 takes [s08](../s08_zoom_cloud_cpu/)'s "single CPU cloud VM" and scales it across many machines. Same numba CPU kernel inside each worker, but frame ranges are fanned across multiple workers writing concurrently to one GCS-backed Zarr.

The interesting deployment-shape question for "multi-CPU" specifically: GKE isn't the right tool for this — Kubernetes + GPU drivers + node-pool autoscaling are all overhead you only need when GPUs are involved. The CPU-only fanout has cleaner options:

| Option | What it is | Tradeoffs |
|---|---|---|
| **Cloud Run Jobs** (likely default) | Serverless containers, runs to completion, parallelisable via task indices | No infrastructure, scales to zero, ~$0 idle. Cold start ~30s. |
| Multiple GCE VMs via Dask | A Dask scheduler + N worker VMs talking over the network | More complex; gives you a real Dask cluster for the demo |
| GCE Managed Instance Group | N identical preemptible VMs, each takes a frame range | Cheap, but each VM has the cold-start tax |

Cloud Run Jobs is the recommended path because it eliminates standing infrastructure and bills only when running. ~$0.05-0.15 to render 120 frames across 4 parallel tasks.

## What its `run.py` would do

Two modes (mirroring [s11](../s11_zoom_fanout_gpu/)'s shape):

- `--mode task`: per-Cloud-Run-task entrypoint. Compute frames `[frame_start, frame_end)` using the s03 / s04 CPU kernel, write to the shared Zarr.
- `--mode dispatch`: control-host driver. Compute frame-range partitioning (`n_frames / n_tasks`) and launch the Cloud Run Job with the right parallelism setting.

## Why it's not implemented today

Stages were re-numbered into a clean 2×2 (machine count × compute type) after the s08 GPU-quota denial pushed us toward CPU-first deployments. s09 is the natural slot for the multi-CPU step in that progression, but isn't blocking anything: s08 (single CPU VM) is what we're deploying today; s11 (multi GPU fan-out) is the deeper architecture lesson.

## Naming convention

The cloud progression in this repo is a 2×2 of two axes: **machine count** × **compute type**.

|  | CPU | GPU |
|---|---|---|
| Single | [s08](../s08_zoom_cloud_cpu/) | [s10](../s10_zoom_cloud_gpu/) |
| Many | **s09** (this stage) | [s11](../s11_zoom_fanout_gpu/) |

Each stage adds exactly one axis over the simpler version. s09 adds machine count to s08; s11 adds GPU to s09 (or equivalently, machine count to s10).
