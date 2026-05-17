# Local development on macOS

The repo is developed on Apple Silicon and deployed in Linux CUDA containers. Most things work natively on the Mac; only a handful of platform-specific decisions are needed.

## Prerequisites

- macOS on Apple Silicon (M1 / M2 / M3 / M4). Intel Macs work for stages 00–04 and 07; the GPU stages need MPS, which is Apple Silicon only.
- `uv` (`brew install uv`) — package manager and venv tool. Provisions Python automatically.
- `ffmpeg` (`brew install ffmpeg`) — for the render step's MP4 stitching.
- (Optional, for stage 08 plumbing tests) Docker Desktop and `kind` (`brew install kind`).

## Install

```bash
uv sync
```

That resolves `uv.lock` and provisions `.venv/`. GPU and cloud dependencies are optional extras — install when you reach those stages:

```bash
uv sync --extra gpu                  # stages 05, 06
uv sync --extra cloud                # stage 08
uv sync --extra gpu --extra cloud    # everything
```

## Stage-by-stage Mac notes

### Stages 00–04, 07 — CPU only

Run directly:

```bash
uv run python -m stages.s00_naive.run
uv run python -m stages.s04_dask_local.run
uv run python -m stages.s07_zoom_local.run
```

Or via the Dagster UI:

```bash
uv run dagster dev -m orchestration.definitions
# Open http://localhost:3000, materialise assets from the graph.
```

### Stage 05 — PyTorch MPS

Native on Apple Silicon. `render/torch_device.py` auto-picks MPS.

```bash
export PYTORCH_ENABLE_MPS_FALLBACK=1   # for any not-yet-implemented MPS op
uv run python -m stages.s05_gpu_torch.run
```

**Precision:** stage 05 runs in float32 throughout — separate real and imag tensors, not complex dtypes. This unifies the CPU / CUDA / MPS code path and sidesteps MPS's historical gaps around complex dtypes. Float32 caps useful zoom at ~10⁶; deep zoom lives in stage 06's shader.

Perf expectation on M-series: ~50–200 Mpixels/sec. Comparable to a low-end discrete GPU, not T4-level, but real-time at 4K for a single frame.

### Stage 06 — GLSL shader

Native. `render/gl_context.py` picks a hidden pygame window on Darwin (Apple's deprecated-but-present OpenGL 4.1 is exactly what the shader targets) and `moderngl.create_standalone_context()` on Linux.

```bash
uv run python -m stages.s06_gpu_shader.run
```

The shader itself is identical across platforms — only the context provider differs.

### Stage 08 — Single cloud VM, CPU

The simplest cloud-deployment shape. Local dev for s08 is "exactly what s07 does, but with s03's CPU kernel and the `--output` is a `gs://` URL." There's no kind cluster, no Dagster K8s executor, no Workload Identity binding — just a multi-frame loop with a remote write target.

You can also run the production shape locally by writing to a local Zarr instead of GCS:

```bash
uv run python -m stages.s08_zoom_cloud_cpu.run \
  --n-frames 120 --output out/s08_local.zarr
```

When ready to deploy, see `stages/s08_zoom_cloud_cpu/README.md` for the VM walkthrough.

### Stages 09 / 10 — Placeholders

`s09_zoom_fanout_cpu` (multi-CPU cloud, likely Cloud Run Jobs) and `s10_zoom_cloud_gpu` (single GPU cloud VM) are placeholders. Their READMEs cover what they would be when implemented. Both are downstream of s08 being exercised first.

### Stage 11 — GKE multi-Pod GPU fan-out

Three local dev modes, in the order you'll likely use them:

| Mode | What you test | When |
|---|---|---|
| Dagster multi-process executor | Asset graph, partition logic, icechunk commit semantics. No K8s at all. | 95% of stage-11 development |
| `kind` cluster | K8s plumbing — pod specs, RBAC, executor config, IOManager wiring. CPU stub for compute (kind has no GPU on Mac). | Before first real GKE deploy |
| Real GKE with T4 pool | Final integration + actual GPU rendering. Spend cloud credit sparingly. | Final verification |

Spin up `kind` locally:

```bash
kind create cluster --config stages/s11_zoom_fanout_gpu/dev/kind-cluster.yaml
# (Dagster K8s executor scaffolding deploys here once stage 11 is built out.)
kind delete cluster --name mandelflow-dev   # when done
```

**Docker Desktop on Mac doesn't pass through the Apple GPU.** A container built for the GKE CUDA pool runs on your Mac via Mesa llvmpipe — very slow. Use that container locally only for "does it compile and start" checks; perf-test only on a real GPU node.

### Stage 12 — FastAPI tile server

```bash
uv run uvicorn stages.s12_viewer_fastapi.main:app --reload
# http://localhost:8000
```

All endpoints are CPU-only — they read a Zarr chunk, apply a colormap, and encode. No GPU, no GL context. Stage 12 reads icechunk repos transparently via `xr.open_zarr`, including time-travel via `/runs/{id}@{commit}/...`.

- `GET /runs` — list materialised Zarrs in the configured store root.
- `GET /runs/{id}/frame/{i}.png` — single frame.
- `GET /tiles/{run_id}/{z}/{x}/{y}.png` — slippy-map tiles from a precomputed pyramid.

On-demand rendering of arbitrary new regions (which would need the stage-06 shader and a long-lived GL context) is out of scope for v1; see DESIGN.md §11.
