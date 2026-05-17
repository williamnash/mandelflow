"""Cross-stage equivalence: every stage matches s00 within tolerance.

Stage 00 (Python triple loop) is the canonical reference. Stages
without `fastmath` must match exactly (tolerance 0). Stages with
fastmath (s03 onward) permit a small percentage of single-iter
differences via `common.testing.assert_iterations_close`.

Add new stages by appending to EXACT_STAGES or FASTMATH_STAGES below.
"""

from __future__ import annotations

import pytest

from common.testing import assert_iterations_close
from stages.s00_naive.compute import compute_frame as s00_compute
from stages.s01_numpy.compute import compute_frame as s01_compute
from stages.s02_numba.compute import compute_frame as s02_compute
from stages.s03_numba_opt.compute import compute_frame as s03_compute
from stages.s04_dask_local.compute import compute_frame as s04_compute

_PARAMS = dict(
    center_re=-0.75,
    center_im=0.0,
    width=3.5,
    resolution=32,
    max_iter=64,
)

EXACT_STAGES = [
    pytest.param(s01_compute, id="s01_numpy"),
    pytest.param(s02_compute, id="s02_numba"),
    pytest.param(s04_compute, id="s04_dask_local"),
]

FASTMATH_STAGES = [
    pytest.param(s03_compute, id="s03_numba_opt"),
]


@pytest.mark.parametrize("compute_frame", EXACT_STAGES)
def test_matches_s00_exactly(compute_frame):
    reference = s00_compute(**_PARAMS)
    actual = compute_frame(**_PARAMS)
    assert_iterations_close(actual, reference,
                            max_pixel_diff_pct=0.0, max_iter_delta=0)


@pytest.mark.parametrize("compute_frame", FASTMATH_STAGES)
def test_matches_s00_within_fastmath_tolerance(compute_frame):
    reference = s00_compute(**_PARAMS)
    actual = compute_frame(**_PARAMS)
    assert_iterations_close(actual, reference,
                            max_pixel_diff_pct=1.0, max_iter_delta=1)
