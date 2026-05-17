"""Stage 04: Dask intra-frame tile fan-out.

Tiles the image into `n_tiles x n_tiles` blocks and dispatches each
block as a `dask.delayed` task. The active Dask scheduler decides
whether tiles run sequentially (synchronous scheduler — the default
for unit tests) or across worker processes (when `run.py` opens a
`Client(LocalCluster())` context).

The per-tile kernel inlines s01's vectorised-numpy logic. We pass
each tile a *slice* of the global linspace rather than re-deriving its
own linspace from centre/width — that keeps s04 bit-identical to s01
(same float discretisation, same escape counts).

The point of this stage is the architecture, not the wall-clock number.
s03's intra-process parallel JIT will beat s04 on a single laptop;
s04's process-based fan-out is the pattern that scales to multiple
machines in stage 07 and onward.
"""

from __future__ import annotations

import dask
import numpy as np

from common.store import ITERATIONS_DTYPE


def _compute_tile(x_slice: np.ndarray, y_slice: np.ndarray, max_iter: int) -> np.ndarray:
    X, Y = np.meshgrid(x_slice, y_slice)
    C = X + 1j * Y
    Z = np.zeros_like(C)
    out = np.full(C.shape, max_iter, dtype=ITERATIONS_DTYPE)
    mask = np.ones(C.shape, dtype=bool)
    for k in range(max_iter):
        Z[mask] = Z[mask] * Z[mask] + C[mask]
        escaped = np.abs(Z) > 2
        out[escaped & mask] = k
        mask &= ~escaped
    return out


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
