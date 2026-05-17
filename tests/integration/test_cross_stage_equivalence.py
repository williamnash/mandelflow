"""Cross-stage equivalence: every stage matches s00 within its own tolerance.

Stage 00 (Python triple loop, float64) is the canonical reference.
Each later stage declares its own tolerance against s00 — IEEE-faithful
stages match exactly; fastmath stages permit a small per-iter delta on
boundary pixels; GPU/float32 stages permit slightly more.

Add new stages by appending a `pytest.param(compute_frame, max_pct,
max_delta, id=...)` row to STAGES.
"""

from __future__ import annotations

import pytest

from common.testing import assert_iterations_close
from render.torch_device import has_gpu
from stages.s00_naive.compute import compute_frame as s00_compute
from stages.s01_numpy.compute import compute_frame as s01_compute
from stages.s02_numba.compute import compute_frame as s02_compute
from stages.s03_numba_opt.compute import compute_frame as s03_compute
from stages.s04_dask_local.compute import compute_frame as s04_compute

try:
    from stages.s05_gpu_torch.compute import compute_frame as s05_compute
except ImportError:
    s05_compute = None

_PARAMS = dict(
    center_re=-0.75,
    center_im=0.0,
    width=3.5,
    resolution=32,
    max_iter=64,
)

# (compute_frame, max_pixel_diff_pct, max_iter_delta)
STAGES = [
    pytest.param(s01_compute, 0.0, 0, id="s01_numpy"),
    pytest.param(s02_compute, 0.0, 0, id="s02_numba"),
    pytest.param(s03_compute, 1.0, 1, id="s03_numba_opt"),
    pytest.param(s04_compute, 1.0, 1, id="s04_dask_local"),
    pytest.param(
        s05_compute, 5.0, 1, id="s05_gpu_torch",
        marks=pytest.mark.skipif(
            not has_gpu(),
            reason="requires torch + GPU (CUDA or MPS); `uv sync --extra gpu`",
        ),
    ),
]


@pytest.mark.parametrize("compute_frame,max_pct,max_delta", STAGES)
def test_matches_s00(compute_frame, max_pct, max_delta):
    reference = s00_compute(**_PARAMS)
    actual = compute_frame(**_PARAMS)
    assert_iterations_close(actual, reference,
                            max_pixel_diff_pct=max_pct,
                            max_iter_delta=max_delta)
