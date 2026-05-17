"""Each stage's CLI writes a valid single-frame Zarr.

Exercises argparse + the stage's `compute_frame` + `common.store` end
to end. Add new stages by appending to STAGE_CLIS.
"""

from __future__ import annotations

import pytest
import xarray as xr

from common.store import ITERATIONS_DTYPE
from stages.s00_naive.run import main as s00_main
from stages.s01_numpy.run import main as s01_main
from stages.s02_numba.run import main as s02_main

STAGE_CLIS = [
    pytest.param(s00_main, id="s00_naive"),
    pytest.param(s01_main, id="s01_numpy"),
    pytest.param(s02_main, id="s02_numba"),
]


@pytest.mark.parametrize("cli_main", STAGE_CLIS)
def test_cli_writes_valid_zarr(cli_main, tmp_path):
    out = tmp_path / "stage.zarr"
    cli_main([
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
