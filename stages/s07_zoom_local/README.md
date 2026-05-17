# Stage 07 — Local multi-frame zoom

**120 frames at 720×720 in 1.36s** on Apple MPS (~11.3 ms/frame). The first multi-frame artifact in the repo: a `(120, 720, 720)` Zarr and the MP4 stitched from it.

s07 isn't a new kernel. It's the **orchestration** stage that unlocks the frame dimension on a single machine.

## What's new at s07

Four things that didn't exist before this stage:

1. **Multi-frame Zarr writes.** Stages 00–06 always wrote `frame=0` into a `(1, H, W)` store. s07 builds an `(N, H, W)` store and uses the region-write pattern from `common/store.py` properly for the first time — one chunk per frame, per-frame metadata (`center_re`, `center_im`, `width`) populated as we go.

2. **The canonical zoom schedule** (`common/schedule.py`). Maps `frame_index → (center_re, center_im, width)` along a **geometric zoom toward Seahorse Valley** (`-0.745, 0.113`). Width shrinks uniformly in log-space (so the visual zoom rate is constant), and the centre walks linearly from the wide canonical view to the target. Frame 0 = the canonical full view; frame N-1 = deep zoom at width 1e-5.

3. **Shared GL context across frames.** s06's `compute_frame` gained an optional `ctx=` kwarg. s07's `run.py` creates the GL context **once**, passes it into every per-frame call, and releases it only at the end. Without this, each frame would pay ~200ms of pygame + moderngl setup; the 120-frame run would take ~25 seconds of pure overhead. With the shared context, that overhead is paid once total.

4. **The MP4 stitcher** (`render/animation.py`). Reads the multi-frame Zarr, renders each frame to a PNG with **global colormap normalisation** (so colours don't flicker as the iteration distribution shifts during the zoom), and pipes the sequence through `ffmpeg` for `libx264 / yuv420p` MP4 output.

## Why no Dask

The original scaffold had this stage named `s07_zoom_dask` — Dask local cluster fanning frames across workers. Renamed because Dask doesn't earn its keep here: on a single laptop with one GPU, parallel frame execution doesn't help. The GPU can only run one s06 dispatch at a time; coordinating "parallel" frames against a single GPU just adds scheduler overhead.

Dask appears at **s04** (intra-frame tiles) and **s08** (inter-frame across a real cluster on GKE). At s07 the win is **shared GL context**, not parallelism.

## How `compute_frame` stays uniform

s07's `compute.py` is a single line:

```python
from stages.s06_gpu_shader.compute import compute_frame
```

The per-frame contract is unchanged — s07 just uses s06's kernel. Everything that makes s07 a distinct stage (schedule, multi-frame Zarr, GL lifecycle, MP4 output) lives in `run.py` and the supporting modules. This is on purpose: when stage 08 swaps the kernel out for distributed compute, only the **driver** changes, never the kernel signature.

## Perf: amortised setup is everything

```
120 frames in 1.36s   (11.3 ms/frame)
```

Compared to s06's standalone ~60ms per frame (which includes context teardown each call), the shared-context loop is **about 5× faster per frame**. The saving is almost entirely GL context lifecycle.

If you wanted to push further:
- The shader program is also recompiled per frame (the `ctx.program(...)` call inside `compute_frame`). Lifting that out — a `ShaderRenderer(ctx)` class — would shave another few ms per frame. Premature for s07; s08 may motivate it.
- For multi-machine throughput, fanning frames across a cluster (s08) gives linear scaling with node count.

## Outputs

```
out/s07_zoom_local.zarr            # (120, 720, 720) uint16 Mandelbrot zoom
out/s07_zoom_local.mp4             # 30 fps animation, ~2 MB
out/s07_zoom_local_frame000.png    # wide view (canonical Mandelbrot)
out/s07_zoom_local_frame119.png    # deep zoom: Seahorse Valley spirals
```

Open the MP4 to see the actual zoom: `open out/s07_zoom_local.mp4`.

## The bend in the contract

s07 is the first stage where `compute.py` is *only* a re-export. The actual stage-level work moved into `run.py`. The single-frame-`compute_frame` contract still holds, just thinly — that's what allows the same Dagster asset wiring to consume any stage uniformly.

## What s08 will add over s07

Same multi-frame contract, same Zarr schema, same kernel — but the frame loop runs across a **Kubernetes pod-per-frame** fan-out via the Dagster K8s executor, writing to a GCS-backed icechunk store. The architecture lesson: *what's different from s07 to s08 isn't the work, it's where it runs.*
