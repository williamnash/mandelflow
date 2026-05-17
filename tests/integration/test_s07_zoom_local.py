"""End-to-end: stage 07 writes a valid multi-frame Zarr."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from common.store import ITERATIONS_DTYPE
from render.gl_context import has_gl

try:
    from stages.s07_zoom_local.run import main as s07_main
except ImportError:
    s07_main = None


@pytest.mark.skipif(
    not has_gl(),
    reason="requires moderngl + pygame + GL drivers; `uv sync --extra gpu`",
)
def test_zoom_writes_multi_frame_zarr(tmp_path):
    out = tmp_path / "zoom.zarr"
    n_frames = 4

    s07_main([
        "--n-frames", str(n_frames),
        "--resolution", "32",
        "--max-iter", "32",
        "--output", str(out),
    ])

    ds = xr.open_zarr(out)
    assert dict(ds.sizes) == {"frame": n_frames, "y": 32, "x": 32}
    assert ds.iterations.dtype == ITERATIONS_DTYPE

    # Per-frame metadata coords are populated for every frame.
    widths = ds.width.values
    assert not np.isnan(widths).any()
    # Geometric zoom: widths monotonically shrink.
    assert np.all(np.diff(widths) < 0)

    # Frame 0 is the wide canonical view — must contain both bounded and escaped pixels.
    # Deep-zoom frames may be entirely inside the set, which is correct math; we only
    # sanity-check that the iteration values are within the valid range for every frame.
    wide = ds.iterations.isel(frame=0).values
    assert (wide == 32).any()
    assert (wide < 32).any()
    for k in range(n_frames):
        arr = ds.iterations.isel(frame=k).values
        assert arr.min() >= 0 and arr.max() <= 32
