"""Stage 04: Dask intra-frame tile fan-out, using s03's optimised kernel.

Each tile is dispatched as a `dask.delayed` task; an active Dask
`Client` (set up by `run.py`) fans tiles across worker *processes*.
Per-tile compute calls s03's single-threaded JIT kernel, so each
worker process does CPU-saturated math without contending with
sibling workers for in-process threads.

Story:
  s02  →  s03: kernel-level wins (fastmath, early exits, etc.)
  s03  →  s04: parallelism — same kernel, fan across worker processes.

The active Dask scheduler decides whether tiles run sequentially
(synchronous scheduler — the default for unit tests) or across worker
processes (when `run.py` opens a `Client(LocalCluster())` context).

Tiles receive *slices* of the global linspace rather than re-deriving
their own linspace from centre+width — that keeps s04 bit-identical
to s03's per-pixel output (same float discretisation, same escape
counts).
"""

from __future__ import annotations

import dask
import numpy as np

from common.store import ITERATIONS_DTYPE
from stages.s03_numba_opt.compute import _instability


def _compute_tile(x_slice: np.ndarray, y_slice: np.ndarray, max_iter: int) -> np.ndarray:
    X, Y = np.meshgrid(x_slice, y_slice)
    C = X + 1j * Y
    return _instability(C, max_iter)


def compute_frame(
    center_re: float,
    center_im: float,
    width: float,
    resolution: int,
    max_iter: int,
    n_tiles: int = 4,
) -> np.ndarray:
    n_tiles = max(1, min(n_tiles, resolution))
    half = width / 2.0
    x = np.linspace(center_re - half, center_re + half, resolution)
    y = np.linspace(center_im - half, center_im + half, resolution)

    boundaries = np.linspace(0, resolution, n_tiles + 1, dtype=int)

    tasks = []
    positions = []
    for ti in range(n_tiles):
        for tj in range(n_tiles):
            y_slice = y[boundaries[ti]:boundaries[ti + 1]]
            x_slice = x[boundaries[tj]:boundaries[tj + 1]]
            tasks.append(dask.delayed(_compute_tile)(x_slice, y_slice, max_iter))
            positions.append((ti, tj))

    results = dask.compute(*tasks)

    out = np.zeros((resolution, resolution), dtype=ITERATIONS_DTYPE)
    for (ti, tj), tile in zip(positions, results):
        out[boundaries[ti]:boundaries[ti + 1],
            boundaries[tj]:boundaries[tj + 1]] = tile
    return out
