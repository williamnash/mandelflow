# Stages

Ten progressively-scaled implementations of the same Mandelbrot
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
| `s06_gpu_shader` | — | — | ModernGL fragment shader on GPU |
| `s07_zoom_dask` | — | — | Unlocks the frame dimension; many frames in parallel |
| `s08_zoom_cloud` | — | — | Dagster K8s executor on GKE writing to GCS |
| `s09_viewer_fastapi` | — | — | Read service over precomputed Zarrs (not a compute stage) |

## Which stage should I use?

The wall-clock champion on a laptop is **s04 dask_local**, but the right pick depends on what you're doing:

| You want… | Use stage |
|---|---|
| The fastest single frame on a laptop | **s04 dask_local** |
| Single-frame compute embedded in another Python script (no cluster) | **s03 numba_opt** |
| Bit-faithful baseline for verification or debugging | **s00 naive** |
| Deep zoom past float32 precision (~10⁶) | s06 gpu_shader |
| Many frames computed across many machines | s07 zoom_dask / s08 zoom_cloud |
| To serve precomputed regions in a browser | s09 viewer_fastapi |

See [`docs/DESIGN.md §12`](../docs/DESIGN.md) for the structural reasoning — per-op dispatch overhead, SIMT control flow, distributed scheduling cost — behind why these picks vary.

## Stage contract

Each compute stage exports `compute_frame(center_re, center_im, width, resolution, max_iter) -> np.ndarray` and a `run.py` CLI. The output dtype is always `uint16`; bounded-set pixels carry the `max_iter` sentinel (see `common/store.py`).

Cross-stage equivalence (every stage matches s00 within tolerance) is asserted in `tests/integration/test_cross_stage_equivalence.py`.
