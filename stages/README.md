# Stages

Thirteen progressively-scaled implementations of the same Mandelbrot
`compute_frame` contract. Each stage swaps the body of one function;
the rest of the system — Zarr schema, CLI plumbing, tests, renderer —
stays identical. That's the pedagogical point: every speedup below is
attributable to the kernel alone.

## Perf comparison

Wall-clock seconds at `resolution=2048`, `max_iter=512`, canonical view
(`center=(-0.75, 0)`, `width=3.5`), on an Apple Silicon laptop.

| Stage | Time | vs s00 | Technique |
|---|---|---|---|
| [`s00_naive`](s00_naive/) | 17.72s | 1× | Pure Python triple loop |
| [`s01_numpy`](s01_numpy/) | 10.79s | 1.6× | Vectorised numpy with mask-tracked escapes |
| [`s02_numba`](s02_numba/) | 1.13s | 15.7× | `@njit` over the per-pixel loop — kills interpreter overhead |
| [`s03_numba_opt`](s03_numba_opt/) | 0.12s | 148× | `@vectorize` + fastmath + cardioid/period-2 early exits (single-threaded — kernel-level wins only) |
| [`s04_dask_local`](s04_dask_local/) | **0.07s** | **253×** | s03's kernel fanned across Dask worker processes — same shape that scales to multi-machine |
| [`s05_gpu_torch`](s05_gpu_torch/) | 1.7s (MPS) | 10.4× | PyTorch on CUDA / MPS, float32 throughout — slower than s03/s04 on Apple integrated GPU; expected to be much faster on CUDA |
| [`s06_gpu_shader`](s06_gpu_shader/) | **0.06s (MPS)** | **295×** | GLSL fragment shader; entire iteration loop in one GPU dispatch — barely scales with image size, unlocks deep zoom |
| [`s07_zoom_local`](s07_zoom_local/) | 1.36s for 120 frames @ 720² | 11.3 ms/frame | Multi-frame zoom on one machine using s06's kernel with shared GL context; produces the first real zoom MP4 |
| [`s08_zoom_cloud_cpu`](s08_zoom_cloud_cpu/) | working | — | Single cloud VM, CPU kernel (s04 = s03 + Dask local cluster for intra-frame fanout). Writes to GCS. |
| [`s09_zoom_fanout_cpu`](s09_zoom_fanout_cpu/) | implemented, validated locally | — | Cloud Run Jobs CPU fan-out, N parallel tasks × s03 numba kernel, writes to a shared icechunk repo in GCS |
| [`s10_zoom_cloud_gpu`](s10_zoom_cloud_gpu/) | placeholder | — | Single cloud VM, GPU kernel (s06); blocked on GCP `GPUS_ALL_REGIONS` quota |
| [`s11_zoom_fanout_gpu`](s11_zoom_fanout_gpu/) | scaffold | — | GKE multi-Pod fan-out, GPU per Pod, writing to a shared GCS Zarr |
| `s12_viewer_fastapi` | — | — | Read service over precomputed Zarrs (not a compute stage) |

## Which stage should I use?

The wall-clock champion on a laptop is **s04 dask_local**, but the right pick depends on what you're doing:

| You want… | Use stage |
|---|---|
| The fastest single frame on a laptop | **s04 dask_local** |
| Single-frame compute embedded in another Python script (no cluster) | **s03 numba_opt** |
| Bit-faithful baseline for verification or debugging | **s00 naive** |
| Deep zoom past float32 precision (~10⁶) | s06 gpu_shader |
| Many frames on a single machine (laptop) | s07 zoom_local |
| Many frames on one cloud machine, CPU (simplest cloud deploy) | s08 zoom_cloud_cpu |
| Many frames across many cloud machines, CPU | s09 zoom_fanout_cpu *(placeholder)* |
| Many frames on one cloud machine, GPU | s10 zoom_cloud_gpu *(placeholder)* |
| Many frames across many cloud machines, GPU | s11 zoom_fanout_gpu |
| To serve precomputed regions in a browser | s12 viewer_fastapi |

See [`docs/DESIGN.md §12`](../docs/DESIGN.md) for the structural reasoning — per-op dispatch overhead, SIMT control flow, distributed scheduling cost — behind why these picks vary.

## Stage contract

Each compute stage exports `compute_frame(center_re, center_im, width, resolution, max_iter) -> np.ndarray` and a `run.py` CLI. The output dtype is always `uint16`; bounded-set pixels carry the `max_iter` sentinel (see `common/store.py`).

Cross-stage equivalence (every stage matches s00 within tolerance) is asserted in `tests/integration/test_cross_stage_equivalence.py`.
