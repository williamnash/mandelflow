"""Stage 03: numba @vectorize, parallel, fastmath, with early-exit checks.

Three optimisations on top of s02:

- `fastmath=True` relaxes IEEE-754 ordering so the compiler can use
  fused multiply-add and reorder accumulations. Allows a small
  per-pixel divergence from s00 near the set boundary — covered by the
  FASTMATH_STAGES tolerance in test_cross_stage_equivalence.
- `target="parallel"` fans the per-pixel kernel across CPU cores via a
  numba prange under the hood. Embarrassingly parallel; near-linear
  scaling with core count.
- Cardioid + period-2 closed-form membership tests bypass the iteration
  loop entirely for points known to be in the set. Together these
  cover the bulk of the set's area, which is where naive iteration
  spends its full `max_iter` budget per pixel.

The iteration loop also unrolls the complex multiplication into real
arithmetic, dropping `abs(z)` (which calls sqrt) for the equivalent
`zr*zr + zi*zi > 4` test.
"""

from __future__ import annotations

import numpy as np
from numba import vectorize


@vectorize(
    ["uint16(complex128, int64)"],
    nopython=True,
    fastmath=True,
    cache=True,
    target="parallel",
)
def _instability(c, max_iter):
    cr = c.real
    ci = c.imag

    cr_shift = cr - 0.25
    q = cr_shift * cr_shift + ci * ci
    if q * (q + cr_shift) < 0.25 * ci * ci:
        return max_iter

    cr_p1 = cr + 1.0
    if cr_p1 * cr_p1 + ci * ci < 0.0625:
        return max_iter

    zr = 0.0
    zi = 0.0
    zr2 = 0.0
    zi2 = 0.0
    for k in range(max_iter):
        zi = 2.0 * zr * zi + ci
        zr = zr2 - zi2 + cr
        zr2 = zr * zr
        zi2 = zi * zi
        if zr2 + zi2 > 4.0:
            return k
    return max_iter


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
    return _instability(C, max_iter)
