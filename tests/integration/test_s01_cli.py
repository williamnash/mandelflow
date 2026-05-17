"""End-to-end: stage 01's CLI writes a valid Zarr."""

from __future__ import annotations

import xarray as xr

from common.store import ITERATIONS_DTYPE
from stages.s01_numpy.run import main


def test_cli_writes_valid_zarr(tmp_path):
    out = tmp_path / "s01.zarr"
    main([
        "--center-re", "-0.75",
        "--center-im", "0.0",
        "--width", "3.5",
        "--resolution", "16",
        "--max-iter", "20",
        "--output", str(out),
    ])

    ds = xr.open_zarr(out)
    assert dict(ds.sizes) == {"frame": 1, "y": 16, "x": 16}
    assert ds.iterations.dtype == ITERATIONS_DTYPE
    assert float(ds.width.isel(frame=0).values) == 3.5

    arr = ds.iterations.isel(frame=0).values
    assert (arr == 20).any()
    assert (arr < 20).any()
