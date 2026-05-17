"""Stage 01: vectorised numpy Mandelbrot.

Same contract as s00; the Python inner loop is gone. Each iteration
updates only pixels that haven't escaped yet (`mask`), which both
short-circuits work and keeps escaped `z` values from compounding into
nonsense.
"""

from __future__ import annotations

import numpy as np

from common.store import ITERATIONS_DTYPE


def compute_frame(
    center_re: float,
    center_im: float,
    width: float,
    resolution: int,
    max_iter: int,
) -> np.ndarray:
    half = width / 2.0
    x = np.linspace(center_re - half, center_re + half, resolution)
    y = np.linspace(center_im - half, center_im + half, resolution)
    X, Y = np.meshgrid(x, y)
    C = X + 1j * Y

    Z = np.zeros_like(C)
    out = np.full(C.shape, max_iter, dtype=ITERATIONS_DTYPE)
    mask = np.ones(C.shape, dtype=bool)

    for k in range(max_iter):
        Z[mask] = Z[mask] * Z[mask] + C[mask]
        escaped = np.abs(Z) > 2
        newly_escaped = escaped & mask
        out[newly_escaped] = k
        mask &= ~escaped

    return out
