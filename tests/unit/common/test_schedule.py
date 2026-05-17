"""Tests for the canonical zoom schedule."""

from __future__ import annotations

import numpy as np

from common.schedule import (
    FINAL_WIDTH,
    INITIAL_CENTER,
    INITIAL_WIDTH,
    TARGET_CENTER,
    canonical_schedule,
)


def test_endpoints_match_named_constants():
    cr, ci, w = canonical_schedule(200)
    assert cr[0] == INITIAL_CENTER[0]
    assert ci[0] == INITIAL_CENTER[1]
    assert w[0] == INITIAL_WIDTH
    assert np.isclose(cr[-1], TARGET_CENTER[0])
    assert np.isclose(ci[-1], TARGET_CENTER[1])
    assert np.isclose(w[-1], FINAL_WIDTH)


def test_width_decreases_monotonically():
    """Geometric zoom — every frame's width must be strictly smaller than the last."""
    _, _, w = canonical_schedule(50)
    assert np.all(np.diff(w) < 0)


def test_width_is_uniform_in_log():
    """Constant-ratio zoom means equal-spaced log(width)."""
    _, _, w = canonical_schedule(100)
    log_diffs = np.diff(np.log(w))
    # Differences should be (very nearly) constant
    assert np.allclose(log_diffs, log_diffs.mean(), rtol=1e-10)


def test_shapes():
    cr, ci, w = canonical_schedule(7)
    assert cr.shape == (7,)
    assert ci.shape == (7,)
    assert w.shape == (7,)


def test_single_frame_returns_initial_view():
    cr, ci, w = canonical_schedule(1)
    assert cr[0] == INITIAL_CENTER[0]
    assert w[0] == INITIAL_WIDTH


def test_zero_frames_rejected():
    import pytest
    with pytest.raises(ValueError):
        canonical_schedule(0)
