"""Tests for the canonical zoom schedule."""

from __future__ import annotations

import numpy as np

from common.schedule import (
    FINAL_WIDTH,
    INITIAL_WIDTH,
    ZOOM_CENTER,
    canonical_schedule,
)


def test_endpoints_match_named_constants():
    cr, ci, w = canonical_schedule(200)
    assert np.isclose(w[0], INITIAL_WIDTH)
    assert np.isclose(w[-1], FINAL_WIDTH)


def test_centre_is_constant():
    """Pure zoom into a fixed point — every frame has the same centre."""
    cr, ci, _ = canonical_schedule(50)
    assert np.all(cr == ZOOM_CENTER[0])
    assert np.all(ci == ZOOM_CENTER[1])


def test_width_decreases_monotonically():
    _, _, w = canonical_schedule(50)
    assert np.all(np.diff(w) < 0)


def test_width_is_uniform_in_log():
    """Log-spaced widths — `np.diff(np.log(w))` should be constant."""
    _, _, w = canonical_schedule(100)
    log_diffs = np.diff(np.log(w))
    assert np.allclose(log_diffs, log_diffs.mean(), rtol=1e-10)


def test_shapes():
    cr, ci, w = canonical_schedule(7)
    assert cr.shape == (7,)
    assert ci.shape == (7,)
    assert w.shape == (7,)


def test_single_frame_returns_initial_width():
    cr, ci, w = canonical_schedule(1)
    assert cr[0] == ZOOM_CENTER[0]
    assert ci[0] == ZOOM_CENTER[1]
    assert np.isclose(w[0], INITIAL_WIDTH)


def test_zero_frames_rejected():
    import pytest
    with pytest.raises(ValueError):
        canonical_schedule(0)


def test_width_overrides_take_effect():
    """Passing initial_width / final_width overrides the module constants."""
    _, _, w = canonical_schedule(10, initial_width=10.0, final_width=1e-5)
    assert np.isclose(w[0], 10.0)
    assert np.isclose(w[-1], 1e-5)


def test_center_override_takes_effect():
    """Passing a `center` overrides ZOOM_CENTER for the schedule."""
    target = (-1.7480368905611776, 0.0)
    cr, ci, _ = canonical_schedule(20, center=target)
    assert np.all(cr == target[0])
    assert np.all(ci == target[1])
