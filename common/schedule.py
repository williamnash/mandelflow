"""Canonical zoom path for the mandelflow demo.

A geometric (constant-ratio) zoom toward a target point. Width shrinks
uniformly in `log(width)` per frame — visually smooth pan/zoom. The
centre walks linearly from the wide-view starting point to the
target, so the camera doesn't drop out of the interesting region as
the view tightens.

`INITIAL_WIDTH = 3.5` and the target = Seahorse Valley
(`-0.745, 0.113`). `FINAL_WIDTH = 1e-4` keeps the per-pixel spacing
(`width / resolution`) safely above ~1e-7 at all sensible
resolutions, which is the practical float32 precision floor — go
deeper and adjacent pixels collide in float space and the shader
produces uniform-color frames (a visible artifact in the MP4).
Deeper zooms need either float64 in the shader or perturbation theory
with a reference orbit; both are out of scope for s06 / s07.
"""

from __future__ import annotations

import numpy as np

INITIAL_CENTER: tuple[float, float] = (-0.75, 0.0)
# `(-0.7435, 0.1314)` is a Seahorse Valley spiral with rich detail at every
# zoom depth — chosen because the linear centre walk through it doesn't
# land in iteration "plateaus" (uniform-iter patches between features), which
# the prior target `(-0.745, 0.113)` did at frames ~97-118.
TARGET_CENTER: tuple[float, float] = (-0.7435, 0.1314)
INITIAL_WIDTH: float = 3.5
# `FINAL_WIDTH = 1e-3` gives a 3,500x zoom — visually impressive while
# keeping the target point centred on recognisable boundary detail. Going
# deeper (e.g. 1e-4) tends to land *inside* the set with the boundary at
# the frame edge — not the payoff a zoom video wants. Deeper zooms need
# hand-tuned waypoint paths anyway; that's beyond s07's scope.
FINAL_WIDTH: float = 1e-3


def canonical_schedule(n_frames: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (center_re, center_im, width) arrays for `n_frames` frames.

    Frame 0 is the wide canonical view; frame `n_frames - 1` is the
    deepest zoom on the target. Iterate the returned arrays in lockstep:
    `for k in range(n_frames): compute_frame(cr[k], ci[k], w[k], ...)`.
    """
    if n_frames < 1:
        raise ValueError(f"n_frames must be >= 1, got {n_frames}")

    if n_frames == 1:
        return (
            np.array([INITIAL_CENTER[0]]),
            np.array([INITIAL_CENTER[1]]),
            np.array([INITIAL_WIDTH]),
        )

    t = np.linspace(0.0, 1.0, n_frames)
    width = INITIAL_WIDTH * (FINAL_WIDTH / INITIAL_WIDTH) ** t
    cr = INITIAL_CENTER[0] + t * (TARGET_CENTER[0] - INITIAL_CENTER[0])
    ci = INITIAL_CENTER[1] + t * (TARGET_CENTER[1] - INITIAL_CENTER[1])
    return cr, ci, width
