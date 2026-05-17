"""Tests for the canonical iterations-Zarr schema."""

from __future__ import annotations

import numpy as np
import xarray as xr

from common.store import ITERATIONS_DTYPE, create_iterations_dataset, write_frame


def test_create_initialises_schema(tmp_path):
    path = tmp_path / "iterations.zarr"
    create_iterations_dataset(path, n_frames=4, resolution=16)

    ds = xr.open_zarr(path)
    assert dict(ds.sizes) == {"frame": 4, "y": 16, "x": 16}
    assert ds.iterations.dtype == ITERATIONS_DTYPE
    assert ds.iterations.encoding["chunks"] == (1, 16, 16)
    assert np.isnan(ds.width.values).all()


def test_write_frame_isolates_writes(tmp_path):
    """Region writes must touch only the targeted frame slot."""
    path = tmp_path / "iterations.zarr"
    create_iterations_dataset(path, n_frames=3, resolution=8)

    iters = np.full((8, 8), 42, dtype=ITERATIONS_DTYPE)
    write_frame(path, frame_index=1, iterations=iters,
                center_re=-0.75, center_im=0.0, width=3.5)

    ds = xr.open_zarr(path)
    assert int(ds.iterations.isel(frame=1).values[0, 0]) == 42
    assert int(ds.iterations.isel(frame=0).values[0, 0]) == 0
    assert float(ds.width.isel(frame=1).values) == 3.5
    assert np.isnan(ds.width.isel(frame=0).values)


def test_write_frame_casts_non_canonical_dtype(tmp_path):
    """A stage returning int32 (or anything else) gets safely coerced."""
    path = tmp_path / "iterations.zarr"
    create_iterations_dataset(path, n_frames=1, resolution=4)

    iters = np.full((4, 4), 100, dtype=np.int32)
    write_frame(path, frame_index=0, iterations=iters,
                center_re=0.0, center_im=0.0, width=1.0)

    ds = xr.open_zarr(path)
    assert ds.iterations.dtype == ITERATIONS_DTYPE
    assert int(ds.iterations.isel(frame=0).values[0, 0]) == 100
