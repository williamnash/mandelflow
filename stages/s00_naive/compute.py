"""Stage 00: naive Python triple-loop reference implementation.

This is the deliberately slow baseline. Pure-Python loops over every
pixel and every iteration, no vectorisation, no JIT — the impl every
later stage measures itself against. Do not optimise.
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
    """Compute one frame of escape iteration counts.

    Each output cell holds the iteration `k` at which `|z_k| > 2` for
    the point `c = x + iy`. Points that never escape within `max_iter`
    iterations receive the sentinel value `max_iter` (the set itself).

    Returns a `(resolution, resolution)` uint16 array with y monotonically
    increasing with row index — i.e. complex-plane orientation, not image
    orientation. The renderer is responsible for any visual flipping.
    """
    half = width / 2.0
    x = np.linspace(center_re - half, center_re + half, resolution)
    y = np.linspace(center_im - half, center_im + half, resolution)
    out = np.zeros((resolution, resolution), dtype=ITERATIONS_DTYPE)

    for i in range(resolution):
        for j in range(resolution):
            c = complex(x[j], y[i])
            z = 0 + 0j
            escape = max_iter
            for k in range(max_iter):
                z = z * z + c
                if abs(z) > 2:
                    escape = k
                    break
            out[i, j] = escape

    return out
