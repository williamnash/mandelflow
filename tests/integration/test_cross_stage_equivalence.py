"""Cross-stage equivalence: stages without fastmath must agree exactly.

Stage 00 (Python triple loop) is the reference. Every later stage gets
checked against it at a small resolution. Stages that don't use
`fastmath` should match exactly (tolerance 0); fastmath-enabled stages
(s03 onward) will permit a small percentage of single-iter differences
via `common.testing.assert_iterations_close`.
"""

from __future__ import annotations

from common.testing import assert_iterations_close
from stages.s00_naive.compute import compute_frame as s00_compute
from stages.s01_numpy.compute import compute_frame as s01_compute

_PARAMS = dict(
    center_re=-0.75,
    center_im=0.0,
    width=3.5,
    resolution=32,
    max_iter=64,
)


def test_s01_matches_s00_exactly():
    """No fastmath, no JIT — these should be bit-identical."""
    reference = s00_compute(**_PARAMS)
    actual = s01_compute(**_PARAMS)
    assert_iterations_close(actual, reference,
                            max_pixel_diff_pct=0.0, max_iter_delta=0)
