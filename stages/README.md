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
| `s05_gpu_torch` | — | — | PyTorch on CUDA / MPS |
| `s06_gpu_shader` | — | — | ModernGL fragment shader on GPU |
| `s07_zoom_dask` | — | — | Unlocks the frame dimension; many frames in parallel |
| `s08_zoom_cloud` | — | — | Dagster K8s executor on GKE writing to GCS |
| `s09_viewer_fastapi` | — | — | Read service over precomputed Zarrs (not a compute stage) |

## Stage contract

Each compute stage exports `compute_frame(center_re, center_im, width, resolution, max_iter) -> np.ndarray` and a `run.py` CLI. The output dtype is always `uint16`; bounded-set pixels carry the `max_iter` sentinel (see `common/store.py`).

Cross-stage equivalence (every stage matches s00 within tolerance) is asserted in `tests/integration/test_cross_stage_equivalence.py`.
