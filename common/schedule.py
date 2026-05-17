"""Canonical zoom path for the mandelflow demo.

A pure geometric zoom *into a fixed centre point* — log-uniform width
schedule, no centre walk. Every frame is centred on the same complex
coordinate; only the view width changes. This matches the standard
Mandelbrot zoom pattern (you converge on a point, you don't pan
across the fractal while zooming).

An earlier version had a linear centre walk from the canonical wide
view `(-0.75, 0)` to the target. That looked smooth in isolation but
produced two visible artifacts in the MP4: (1) the camera passed
through "iteration plateaus" — uniform-colour patches between
features along the path — which read as out-of-order flickering, and
(2) the resulting motion was a pan-and-zoom rather than a true zoom,
which broke the visual illusion. Fixed centre, log widths is the
backend-live-challenge / canonical Mandelbrot-zoom pattern.

`ZOOM_CENTER = (-0.7435, 0.1314)` is a Seahorse Valley spiral with
rich detail at every zoom depth. `FINAL_WIDTH = 1e-3` gives a 3,500x
zoom while staying safely inside float32's useful precision range
(`width / resolution` stays well above the float32 floor ~1e-7).
Deeper zooms need float64 in the shader or perturbation theory.
"""

from __future__ import annotations

import numpy as np

ZOOM_CENTER: tuple[float, float] = (-0.7435, 0.1314)
INITIAL_WIDTH: float = 3.5
FINAL_WIDTH: float = 1e-3


def canonical_schedule(n_frames: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (center_re, center_im, width) arrays for `n_frames` frames.

    Centre is constant — `ZOOM_CENTER` repeated `n_frames` times. Width
    is log-spaced from `INITIAL_WIDTH` to `FINAL_WIDTH`. Iterate in
    lockstep: `for k in range(n_frames): compute_frame(cr[k], ci[k], w[k], ...)`.
    """
    if n_frames < 1:
        raise ValueError(f"n_frames must be >= 1, got {n_frames}")

    if n_frames == 1:
        width = np.array([INITIAL_WIDTH])
    else:
        width = np.logspace(np.log10(INITIAL_WIDTH), np.log10(FINAL_WIDTH), n_frames)

    cr = np.full(n_frames, ZOOM_CENTER[0])
    ci = np.full(n_frames, ZOOM_CENTER[1])
    return cr, ci, width
