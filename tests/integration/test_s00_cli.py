"""End-to-end: stage 00's CLI writes a valid Zarr that opens cleanly.

Exercises compute_frame, common.store, and the argparse plumbing
together. Kept at tiny resolution so it finishes in well under a second.
"""

from __future__ import annotations

import xarray as xr

from common.store import ITERATIONS_DTYPE
from stages.s00_naive.run import main


def test_cli_writes_valid_zarr(tmp_path):
    out = tmp_path / "s00.zarr"
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
    assert float(ds.center_re.isel(frame=0).values) == -0.75

    arr = ds.iterations.isel(frame=0).values
    assert (arr == 20).any(), "expected some in-set pixels at canonical view"
    assert (arr < 20).any(), "expected some escaped pixels at canonical view"
