"""Stage 02: numba @njit over the per-pixel iteration.

Same Python triple loop as s00 — but the inner two loops are compiled
to native code via numba.njit. No fastmath, no vectorise; this stage
shows how much of s00's cost was the Python interpreter, separate from
the cost of the math itself.

The JIT kernel lives at module scope so `cache=True` can persist the
compiled artifact under __pycache__/. First call after a clean
checkout pays the compile cost (~1-2s); subsequent calls do not.
"""

from __future__ import annotations

import numpy as np
from numba import njit

from common.store import ITERATIONS_DTYPE


@njit(cache=True)
def _kernel(x, y, max_iter, out):
    resolution = out.shape[0]
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
    out = np.zeros((resolution, resolution), dtype=ITERATIONS_DTYPE)
    _kernel(x, y, max_iter, out)
    return out
