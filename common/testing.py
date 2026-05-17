"""Test helpers shared across stages.

`assert_iterations_close` is the canonical equivalence check for Mandelbrot
iteration arrays. Different stages produce slightly different iteration counts
near the set boundary (one extra iteration can flip a pixel between escaped
and bounded), so exact equality is too strict for cross-stage comparisons.
The tolerance allows a small fraction of pixels to differ by a small number
of iterations.

Tolerance defaults are conservative; tighten per-stage if a stage is expected
to match the reference exactly (e.g. stages 00, 01, 02 without fastmath).
"""

from __future__ import annotations

import numpy as np


def assert_iterations_close(
    actual: np.ndarray,
    expected: np.ndarray,
    max_pixel_diff_pct: float = 1.0,
    max_iter_delta: int = 1,
) -> None:
    """Assert two iteration arrays are equivalent within tolerance.

    Args:
        actual: iterations array produced by the stage under test.
        expected: reference iterations array (typically stage 00's output
            at the same center / width / resolution / max_iter).
        max_pixel_diff_pct: maximum percentage of pixels allowed to differ
            by more than `max_iter_delta` iterations.
        max_iter_delta: per-pixel iteration count tolerance.

    Raises:
        AssertionError if the shape mismatches or divergence exceeds tolerance.
    """
    if actual.shape != expected.shape:
        raise AssertionError(
            f"shape mismatch: actual {actual.shape}, expected {expected.shape}"
        )
    delta = np.abs(actual.astype(np.int32) - expected.astype(np.int32))
    differing = int((delta > max_iter_delta).sum())
    total = actual.size
    pct = 100.0 * differing / total
    if pct > max_pixel_diff_pct:
        raise AssertionError(
            f"{differing}/{total} pixels ({pct:.2f}%) differ by more than "
            f"{max_iter_delta} iteration(s) — exceeds tolerance of "
            f"{max_pixel_diff_pct:.2f}%"
        )
