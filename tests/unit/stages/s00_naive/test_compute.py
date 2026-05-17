"""Tests for stage 00's naive triple-loop kernel."""

from __future__ import annotations

from common.store import ITERATIONS_DTYPE
from stages.s00_naive.compute import compute_frame


def test_shape_and_dtype():
    arr = compute_frame(-0.5, 0.0, 2.0, 8, 32)
    assert arr.shape == (8, 8)
    assert arr.dtype == ITERATIONS_DTYPE


def test_origin_is_in_set():
    """c=0 satisfies z=z*z+c trivially; should hit the max_iter sentinel."""
    arr = compute_frame(0.0, 0.0, 1.0, 1, 100)
    assert int(arr[0, 0]) == 100


def test_far_point_escapes_immediately():
    """|c| > 2 escapes on the first iteration (z=0 → z=c, |z|=|c|>2)."""
    arr = compute_frame(10.0, 0.0, 1.0, 1, 100)
    assert int(arr[0, 0]) == 0


def test_view_contains_both_in_set_and_escaped_pixels():
    """At the canonical full view, the image must contain both bounded
    and escaped pixels — sanity that the kernel isn't all-zero or all-max."""
    arr = compute_frame(-0.75, 0.0, 3.5, 16, 50)
    assert (arr == 50).any(), "no in-set pixels found"
    assert (arr < 50).any(), "no escaped pixels found"
