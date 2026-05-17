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

`ZOOM_CENTER` is a Seahorse Valley spiral, pinned to full float64
precision so deep zooms land on the boundary at every scale rather
than in iteration plateaus. `FINAL_WIDTH = 1e-3` gives a 3,500×
zoom by default — safely inside float32's useful precision range
for s06/s07. CPU stages (float64) can pass a much deeper
`final_width` argument; see `canonical_schedule` below.
"""

from __future__ import annotations

import numpy as np

# `ZOOM_CENTER` is on the Seahorse Valley spiral, to full float64 precision.
# Picked specifically so that zooms of arbitrary depth (up to float64's ~1e-13
# limit) land on real boundary structure rather than iteration plateaus.
# Earlier we used the rounded `(-0.7435, 0.1314)` — fine for shallow zoom
# (down to ~1e-4) but lands in flat regions deeper than that.
ZOOM_CENTER: tuple[float, float] = (-0.743643887037151, 0.131825904205330)
INITIAL_WIDTH: float = 3.5
FINAL_WIDTH: float = 1e-3


def canonical_schedule(
    n_frames: int,
    initial_width: float = INITIAL_WIDTH,
    final_width: float = FINAL_WIDTH,
    center: tuple[float, float] = ZOOM_CENTER,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (center_re, center_im, width) arrays for `n_frames` frames.

    Centre is constant — `center` repeated `n_frames` times. Width is
    log-spaced from `initial_width` to `final_width`. Defaults match the
    float32-safe range (`1e-3` final) and the Seahorse Valley spiral.

    For deep zoom on CPU (float64): pass `final_width` down to ~1e-10
    AND pick `center` precisely on a self-similar feature of the set,
    not just near one. The default centre is good to ~1e-4; for deeper,
    use a known boundary point such as
    `(-0.743643887037151, 0.131825904205330)` — Seahorse Valley to full
    float64 precision — or other classic deep-zoom destinations.
    """
    if n_frames < 1:
        raise ValueError(f"n_frames must be >= 1, got {n_frames}")

    if n_frames == 1:
        width = np.array([initial_width])
    else:
        width = np.logspace(np.log10(initial_width), np.log10(final_width), n_frames)

    cr = np.full(n_frames, center[0])
    ci = np.full(n_frames, center[1])
    return cr, ci, width
