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

# The store formats open_iterations_dataset can dispatch on. Anything
# listing or filtering runs (e.g. the stage-12 viewer) keys off this.
STORE_SUFFIXES = (".zarr", ".icechunk")

# The object-store schemes the repo supports, in one place. Every
# "is this remote?" check and every storage factory keys off this —
# scheme dispatch copy-pasted per call site is how the IOManagers
# silently missed s3:// support while the stages gained it.
OBJECT_STORE_SCHEMES = ("gs://", "s3://")


def is_object_store_path(path: str | Path) -> bool:
    return str(path).startswith(OBJECT_STORE_SCHEMES)


def _split_bucket_prefix(path_str: str) -> tuple[str, str]:
    bucket_and_prefix = path_str.split("://", 1)[1]
    parts = bucket_and_prefix.split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def icechunk_storage(path: str | Path):
    """The one scheme → icechunk storage mapping.

    Shared by every icechunk opener (read-side `open_iterations_dataset`,
    s09's task `_open_repo`, the Dagster IcechunkFrameIOManager) so a new
    backend or a storage-kwarg change lands everywhere at once. AWS
    credentials and region come from the environment (`from_env=True`);
    the preflight in common/aws.py checks both up front.
    """
    import icechunk

    path_str = str(path).rstrip("/")
    if path_str.startswith("gs://"):
        bucket, prefix = _split_bucket_prefix(path_str)
        return icechunk.gcs_storage(bucket=bucket, prefix=prefix)
    if path_str.startswith("s3://"):
        bucket, prefix = _split_bucket_prefix(path_str)
        return icechunk.s3_storage(bucket=bucket, prefix=prefix, from_env=True)
    return icechunk.local_filesystem_storage(path_str)


def open_iterations_dataset(path: str | Path) -> xr.Dataset:
    """Open an iterations dataset from raw Zarr or an icechunk repo.

    Detects icechunk by the `.icechunk` suffix on the path. Both backends
    expose an xarray-compatible Zarr store; the only difference is how we
    obtain it (raw-zarr opens directly; icechunk opens a readonly session
    on the `main` branch and uses its store). Accepted path shapes:

      - `path/to/run.{zarr,icechunk}`         → local FS
      - `gs://bucket/run.{zarr,icechunk}`     → GCS (gcsfs / icechunk)
      - `s3://bucket/run.{zarr,icechunk}`     → S3 (s3fs / icechunk)

    AWS credentials resolve via the standard chain (env vars, profile,
    instance role); GCP via Application Default Credentials.
    """
    path_str = str(path).rstrip("/")
    if path_str.endswith(".icechunk"):
        import icechunk

        repo = icechunk.Repository.open(icechunk_storage(path_str))
        return xr.open_zarr(repo.readonly_session("main").store)
    return xr.open_zarr(path_str)


def list_stores(root: str | Path) -> list[str]:
    """Names of openable stores directly under `root` (sorted).

    A store is anything `open_iterations_dataset` can dispatch on —
    see STORE_SUFFIXES. Roots may be a local directory, `gs://…`, or
    `s3://…`; a missing local root lists as empty rather than raising
    (the viewer treats "nothing there yet" as a normal state).
    """
    root_str = str(root).rstrip("/")
    if is_object_store_path(root_str):
        import fsspec

        scheme, rest = root_str.split("://", 1)
        fs = fsspec.filesystem(scheme)
        try:
            entries = fs.ls(rest)
        except FileNotFoundError:
            return []
        return sorted(
            e.rstrip("/").rsplit("/", 1)[-1]
            for e in entries
            if e.rstrip("/").endswith(STORE_SUFFIXES)
        )
    root_path = Path(root_str)
    if not root_path.is_dir():
        return []
    return sorted(p.name for p in root_path.iterdir() if p.name.endswith(STORE_SUFFIXES))


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
