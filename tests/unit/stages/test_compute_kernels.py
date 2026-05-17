"""Per-stage `compute_frame` contract tests.

Every CPU compute stage satisfies the same kernel contract: correct
shape and dtype, correct encoding of bounded vs immediately-escaping
points, and a non-degenerate output at the canonical view.

Add new stages by appending to STAGES below — the four contract tests
fan out automatically.
"""

from __future__ import annotations

import pytest

from common.store import ITERATIONS_DTYPE
from render.gl_context import has_gl
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

try:
    from stages.s06_gpu_shader.compute import compute_frame as s06_compute
except ImportError:
    s06_compute = None

STAGES = [
    pytest.param(s00_compute, id="s00_naive"),
    pytest.param(s01_compute, id="s01_numpy"),
    pytest.param(s02_compute, id="s02_numba"),
    pytest.param(s03_compute, id="s03_numba_opt"),
    pytest.param(s04_compute, id="s04_dask_local"),
    pytest.param(
        s05_compute, id="s05_gpu_torch",
        marks=pytest.mark.skipif(
            not has_gpu(),
            reason="requires torch + GPU (CUDA or MPS); `uv sync --extra gpu`",
        ),
    ),
    pytest.param(
        s06_compute, id="s06_gpu_shader",
        marks=pytest.mark.skipif(
            not has_gl(),
            reason="requires moderngl + pygame + GL drivers; `uv sync --extra gpu`",
        ),
    ),
]


@pytest.mark.parametrize("compute_frame", STAGES)
def test_shape_and_dtype(compute_frame):
    arr = compute_frame(-0.5, 0.0, 2.0, 8, 32)
    assert arr.shape == (8, 8)
    assert arr.dtype == ITERATIONS_DTYPE


@pytest.mark.parametrize("compute_frame", STAGES)
def test_origin_is_in_set(compute_frame):
    """c=0 satisfies z=z*z+c trivially; should hit the max_iter sentinel."""
    arr = compute_frame(0.0, 0.0, 1.0, 1, 100)
    assert int(arr[0, 0]) == 100


@pytest.mark.parametrize("compute_frame", STAGES)
def test_far_point_escapes_immediately(compute_frame):
    """|c| > 2 escapes on the first iteration (z=0 → z=c, |z|=|c|>2)."""
    arr = compute_frame(10.0, 0.0, 1.0, 1, 100)
    assert int(arr[0, 0]) == 0


@pytest.mark.parametrize("compute_frame", STAGES)
def test_view_contains_both_in_set_and_escaped_pixels(compute_frame):
    """At the canonical full view, the image must contain a mix."""
    arr = compute_frame(-0.75, 0.0, 3.5, 16, 50)
    assert (arr == 50).any()
    assert (arr < 50).any()
