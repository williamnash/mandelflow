"""Stage 03: numba @vectorize with fastmath + cardioid/period-2 early exits.

Kernel-level optimisations only — no parallelism. The story across
stages is one optimisation per stage:
  s02  →  s03: kernel-level wins (this stage)
  s03  →  s04: parallelism (Dask process fan-out)

Three kernel optimisations on top of s02:

- `fastmath=True` relaxes IEEE-754 ordering so the compiler can use
  fused multiply-add and reorder accumulations. Allows a small
  per-pixel divergence from s00 near the set boundary — covered by the
  FASTMATH_STAGES tolerance in test_cross_stage_equivalence.
- Cardioid + period-2 closed-form membership tests bypass the iteration
  loop entirely for points known to be in the set. Together these
  cover the bulk of the set's area, which is where naive iteration
  spends its full `max_iter` budget per pixel.
- The iteration loop unrolls the complex multiplication into real
  arithmetic, dropping `abs(z)` (which calls sqrt) for the equivalent
  `zr*zr + zi*zi > 4` test.

This kernel is consumed directly by s04, which fans it across worker
processes via Dask. Keeping it single-threaded here avoids nested
parallelism (numba-parallel-inside-Dask-worker would oversubscribe
cores).
"""

from __future__ import annotations

import numpy as np
from numba import vectorize


@vectorize(
    ["uint16(complex128, int64)"],
    nopython=True,
    fastmath=True,
    cache=True,
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
