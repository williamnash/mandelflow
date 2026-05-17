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
    max_iter = 64

    s07_main([
        "--n-frames", str(n_frames),
        "--resolution", "32",
        "--max-iter", str(max_iter),
        "--output", str(out),
    ])

    ds = xr.open_zarr(out)
    assert dict(ds.sizes) == {"frame": n_frames, "y": 32, "x": 32}
    assert ds.iterations.dtype == ITERATIONS_DTYPE

    # Per-frame metadata coords are populated for every frame.
    widths = ds.width.values
    assert not np.isnan(widths).any()
    assert np.all(np.diff(widths) < 0)  # geometric zoom

    # Fixed-centre zoom: every frame is centred on the same complex coordinate.
    assert np.all(ds.center_re.values == ds.center_re.values[0])
    assert np.all(ds.center_im.values == ds.center_im.values[0])

    # At max_iter=64 every frame in the schedule (wide view through 3500x zoom on
    # the Seahorse spiral) contains both bounded and escaped pixels.
    for k in range(n_frames):
        arr = ds.iterations.isel(frame=k).values
        assert (arr == max_iter).any(), f"frame {k} has no in-set pixels"
        assert (arr < max_iter).any(), f"frame {k} has no escaped pixels"
