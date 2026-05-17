"""s08's per-frame compute.

Imports from **s04** (`s03 kernel + Dask intra-frame tile fanout`)
rather than directly from s03. This means each frame is computed using
all available CPU cores via Dask: the frame's grid is split into
`n_tiles × n_tiles` blocks, dispatched as `dask.delayed` tasks, and
the active scheduler (set up by `run.py` via `LocalCluster` + `Client`)
runs them in parallel worker processes.

On the laptop: 8+ cores × s03 fastmath kernel per tile is dramatically
faster than s03 alone (the latter pegs one core at 100% while the
others idle).

On a small cloud VM (e2-standard-2 = 2 cores): the speedup is modest
but Dask's process overhead is still smaller than the compute savings
for deep-zoom frames.

If/when we want the GPU shader, swap this import to
`stages.s06_gpu_shader.compute` — float32 limits but ~10× faster again
on the GPU stages where it's applicable.
"""

from stages.s04_dask_local.compute import compute_frame

__all__ = ["compute_frame"]
