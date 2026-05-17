"""Zarr-backed dataset schema for Mandelbrot iteration arrays.

The data product across all stages is a `(frame, y, x)` uint16 array of
escape iteration counts. Chunks are `(1, H, W)` — one chunk per frame —
so per-frame writers never contend on chunk boundaries.

Per-frame metadata (center, width) is stored as coordinates on the
`frame` axis, enabling `ds.sel(frame=i)` and post-hoc width-indexed
selection.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

ITERATIONS_DTYPE = np.uint16


def create_iterations_dataset(
    path: str | Path,
    n_frames: int,
    resolution: int,
) -> None:
    """Initialise an empty Zarr store with the canonical schema.

    Allocates the full `(n_frames, resolution, resolution)` iteration
    array. Per-frame writers fill it in via `write_frame`. Per-frame
    metadata coords start at NaN to mark "not yet materialised".
    """
    iterations = np.zeros(
        (n_frames, resolution, resolution), dtype=ITERATIONS_DTYPE
    )
    ds = xr.Dataset(
        data_vars={
            "iterations": (("frame", "y", "x"), iterations),
        },
        coords={
            "frame": np.arange(n_frames, dtype=np.int32),
            "center_re": ("frame", np.full(n_frames, np.nan)),
            "center_im": ("frame", np.full(n_frames, np.nan)),
            "width": ("frame", np.full(n_frames, np.nan)),
        },
    )
    encoding = {
        "iterations": {"chunks": (1, resolution, resolution)},
    }
    ds.to_zarr(path, mode="w", encoding=encoding, zarr_format=3)


def write_frame(
    path: str | Path,
    frame_index: int,
    iterations: np.ndarray,
    center_re: float,
    center_im: float,
    width: float,
) -> None:
    """Write one frame's iteration array and metadata into the store.

    Uses Zarr region writes so multiple frame writers can run in parallel
    in later stages without coordinating on chunk boundaries — each frame
    occupies its own `(1, H, W)` chunk.
    """
    if iterations.dtype != ITERATIONS_DTYPE:
        iterations = iterations.astype(ITERATIONS_DTYPE)
    ds_frame = xr.Dataset(
        data_vars={
            "iterations": (("frame", "y", "x"), iterations[None, :, :]),
        },
        coords={
            "frame": np.array([frame_index], dtype=np.int32),
            "center_re": ("frame", np.array([center_re])),
            "center_im": ("frame", np.array([center_im])),
            "width": ("frame", np.array([width])),
        },
    )
    ds_frame.to_zarr(
        path,
        region={"frame": slice(frame_index, frame_index + 1)},
    )
