"""Tests for stage 01's vectorised-numpy kernel."""

from __future__ import annotations

from common.store import ITERATIONS_DTYPE
from stages.s01_numpy.compute import compute_frame


def test_shape_and_dtype():
    arr = compute_frame(-0.5, 0.0, 2.0, 8, 32)
    assert arr.shape == (8, 8)
    assert arr.dtype == ITERATIONS_DTYPE


def test_origin_is_in_set():
    arr = compute_frame(0.0, 0.0, 1.0, 1, 100)
    assert int(arr[0, 0]) == 100


def test_far_point_escapes_immediately():
    arr = compute_frame(10.0, 0.0, 1.0, 1, 100)
    assert int(arr[0, 0]) == 0


def test_view_contains_both_in_set_and_escaped_pixels():
    arr = compute_frame(-0.75, 0.0, 3.5, 16, 50)
    assert (arr == 50).any()
    assert (arr < 50).any()
