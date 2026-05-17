"""s09's per-frame compute is s03's — single-thread numba.

Cloud Run Jobs gives each task its own container with limited cores
(2 vCPU by default). Using s04's Dask layer inside that would add
process overhead without much speedup. The outer parallelism for
s09 comes from spawning N tasks via Cloud Run Jobs — set by the
dispatcher in `run.py` — where each task is single-threaded numba
on one frame range.

If you wanted to bump per-task parallelism (e.g., 8 vCPU tasks),
swap this import to `stages.s04_dask_local.compute` and the rest
of the stage is unchanged.
"""

from stages.s03_numba_opt.compute import compute_frame

__all__ = ["compute_frame"]
