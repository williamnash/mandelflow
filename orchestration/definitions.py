"""Dagster orchestration for mandelflow.

The minimum viable Dagster setup that the design docs have been promising:
one frame-partitioned `iterations` asset, bound to a compute stage's
`compute_frame` function, with a custom `IOManager` that writes per-frame
chunks to a Zarr store via `common.store.write_frame`.

Run the UI locally with:

    uv run dagster dev -m orchestration.definitions

Then open <http://localhost:3000>. The asset graph shows `iterations`
partitioned across N_FRAMES. Click "Materialize all" to compute every
frame; Dagster's multiprocess executor parallelises across partitions.

Architectural notes (DESIGN.md §3):
- Partitions ≡ frames. The single `iterations` asset has one partition
  per frame index.
- IOManager ≡ storage. `ZarrFrameIOManager` writes to whatever path is
  configured — local FS or `gs://` (xarray + gcsfs handle both).
- Executor swap is the only diff between local and cluster runs.
  Currently `multiprocess_executor` (laptop); s11 will swap to
  `k8s_job_executor` (one Pod per partition) with the same asset code.

This module is intentionally small. Pick the kernel by changing the
`compute_frame` import; everything else stays the same.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import xarray as xr
from dagster import (
    ConfigurableIOManager,
    Definitions,
    InputContext,
    OutputContext,
    StaticPartitionsDefinition,
    asset,
    multiprocess_executor,
)

from common.schedule import canonical_schedule
from common.store import ITERATIONS_DTYPE, create_iterations_dataset, write_frame
from stages.s07_zoom_local.compute import compute_frame

# Configuration. Bump these to do a bigger run; partition count is fixed
# at module load time, so changing N_FRAMES means restarting `dagster dev`.
N_FRAMES = 120
RESOLUTION = 720
MAX_ITER = 1024
ZARR_PATH = "out/dagster_run.zarr"
ICECHUNK_PATH = os.environ.get(
    "MANDELFLOW_ICECHUNK_PATH", "out/dagster_run.icechunk"
)


frame_partitions = StaticPartitionsDefinition(
    [f"{i:04d}" for i in range(N_FRAMES)]
)


class ZarrFrameIOManager(ConfigurableIOManager):
    """Persist each materialised partition as one frame in a shared Zarr.

    Lazily initialises the Zarr store on first write — the store has
    `n_frames` slots pre-allocated, region-write semantics, and the
    schema from `common/store.py`. Same code works for local paths
    (`out/foo.zarr`) and `gs://bucket/foo.zarr` (xarray + gcsfs).
    """

    path: str
    n_frames: int
    resolution: int

    def _ensure_dataset(self) -> None:
        # Local paths: check for the directory; gs:// paths: try-and-write
        # is the only portable check. For now, simple local check.
        is_gcs = self.path.startswith("gs://")
        if not is_gcs and Path(self.path).exists():
            return
        create_iterations_dataset(self.path, self.n_frames, self.resolution)

    def handle_output(self, context: OutputContext, obj: np.ndarray) -> None:
        self._ensure_dataset()
        k = int(context.partition_key)
        cr, ci, w = canonical_schedule(self.n_frames)
        write_frame(
            self.path,
            frame_index=k,
            iterations=obj,
            center_re=float(cr[k]),
            center_im=float(ci[k]),
            width=float(w[k]),
        )
        context.log.info(f"wrote frame {k} ({obj.shape}, iter range "
                         f"[{int(obj.min())}..{int(obj.max())}])")

    def load_input(self, context: InputContext) -> np.ndarray:
        ds = xr.open_zarr(self.path)
        return ds.iterations.isel(frame=int(context.partition_key)).values


class IcechunkFrameIOManager(ConfigurableIOManager):
    """Persist each materialised partition as one icechunk commit.

    Each partition opens a writable session, writes its frame chunk via
    region-write, and commits with a descriptive message. The data-lineage
    history is then the icechunk commit history — and that maps 1:1 onto
    Dagster's materialisation event log. This is the architectural payoff
    that DESIGN.md §7 has been promising.

    Works for local filesystem paths (e.g. `out/run.icechunk`) and for
    `gs://bucket/prefix` URLs. For S3 / Azure / R2 / Tigris, swap the
    storage backend in `_open_repo`.

    For s09 (multi-machine Cloud Run Jobs writing concurrently), this is
    the right IOManager: icechunk's transactional commits handle the
    parallel-write semantics that raw Zarr can't. The dispatcher opens
    `Repository.open_or_create` once *before* fanning out tasks (per
    icechunk's parallel-write guide — open_or_create is NOT safe to
    race across processes); each task then opens a session on the
    existing repo.
    """

    path: str
    n_frames: int
    resolution: int

    def _open_repo(self):
        import icechunk
        if self.path.startswith("gs://"):
            parts = self.path[5:].split("/", 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""
            storage = icechunk.gcs_storage(bucket=bucket, prefix=prefix)
        else:
            Path(self.path).mkdir(parents=True, exist_ok=True)
            storage = icechunk.local_filesystem_storage(self.path)
        return icechunk.Repository.open_or_create(storage)

    def _ensure_schema(self, repo) -> None:
        """Initialise the dataset schema if the repo is empty.

        Idempotent: if `iterations` already exists at the head of `main`,
        does nothing. Otherwise writes the pre-allocated `(N, H, W)`
        array (zeros + NaN coords) and commits the schema.
        """
        try:
            session = repo.readonly_session("main")
            ds = xr.open_zarr(session.store)
            if "iterations" in ds.data_vars:
                return
        except Exception:
            pass  # repo empty or main has no commits — fall through to init

        iterations = np.zeros(
            (self.n_frames, self.resolution, self.resolution), dtype=ITERATIONS_DTYPE
        )
        ds = xr.Dataset(
            data_vars={"iterations": (("frame", "y", "x"), iterations)},
            coords={
                "frame": np.arange(self.n_frames, dtype=np.int32),
                "center_re": ("frame", np.full(self.n_frames, np.nan)),
                "center_im": ("frame", np.full(self.n_frames, np.nan)),
                "width": ("frame", np.full(self.n_frames, np.nan)),
            },
        )
        encoding = {
            "iterations": {"chunks": (1, self.resolution, self.resolution)},
        }
        session = repo.writable_session("main")
        ds.to_zarr(session.store, mode="w", encoding=encoding, zarr_format=3)
        session.commit("initialize iterations dataset schema")

    def handle_output(self, context: OutputContext, obj: np.ndarray) -> None:
        repo = self._open_repo()
        self._ensure_schema(repo)
        k = int(context.partition_key)
        cr, ci, w = canonical_schedule(self.n_frames)

        ds_frame = xr.Dataset(
            data_vars={
                "iterations": (
                    ("frame", "y", "x"),
                    obj.astype(ITERATIONS_DTYPE)[None, :, :],
                )
            },
            coords={
                "frame": np.array([k], dtype=np.int32),
                "center_re": ("frame", np.array([float(cr[k])])),
                "center_im": ("frame", np.array([float(ci[k])])),
                "width": ("frame", np.array([float(w[k])])),
            },
        )
        session = repo.writable_session("main")
        ds_frame.to_zarr(session.store, region={"frame": slice(k, k + 1)})
        snapshot = session.commit(f"frame {k:04d}")
        context.log.info(
            f"icechunk: wrote frame {k} ({obj.shape}, iter range "
            f"[{int(obj.min())}..{int(obj.max())}]); commit {snapshot[:8] if isinstance(snapshot, str) else snapshot}"
        )

    def load_input(self, context: InputContext) -> np.ndarray:
        repo = self._open_repo()
        session = repo.readonly_session("main")
        return xr.open_zarr(session.store).iterations.isel(
            frame=int(context.partition_key)
        ).values


def _select_io_manager():
    """Pick the IOManager based on MANDELFLOW_STORAGE env var.

    `zarr` (default): raw Zarr at ZARR_PATH. Fine for the local Dagster
    demo — partitions write disjoint chunks so there's no contention.
    `icechunk`: icechunk-backed Zarr at ICECHUNK_PATH. The architectural
    target for s09 / s11 where multiple writers actually contend; each
    partition becomes one commit.
    """
    storage = os.environ.get("MANDELFLOW_STORAGE", "zarr").lower()
    if storage == "icechunk":
        return IcechunkFrameIOManager(
            path=ICECHUNK_PATH,
            n_frames=N_FRAMES,
            resolution=RESOLUTION,
        )
    return ZarrFrameIOManager(
        path=ZARR_PATH,
        n_frames=N_FRAMES,
        resolution=RESOLUTION,
    )


@asset(partitions_def=frame_partitions, io_manager_key="zarr_io")
def iterations(context) -> np.ndarray:
    """One frame of the Mandelbrot iteration array for the partitioned index.

    The kernel comes from `stages.s07_zoom_local.compute` (which is itself
    a re-export of s06's GPU shader). Swap the import at the top of this
    module to test other kernels — the IOManager and partition shape stay
    the same.
    """
    k = int(context.partition_key)
    cr, ci, w = canonical_schedule(N_FRAMES)
    context.log.info(
        f"computing frame {k} of {N_FRAMES}: "
        f"center=({cr[k]}, {ci[k]}) width={w[k]:.3g}"
    )
    return compute_frame(
        float(cr[k]), float(ci[k]), float(w[k]),
        RESOLUTION, MAX_ITER,
    )


defs = Definitions(
    assets=[iterations],
    # multiprocess_executor parallelises partitions across N OS processes.
    # For s11 (GKE fan-out) this becomes k8s_job_executor from dagster-k8s,
    # one Pod per partition. Same asset code; only the executor changes.
    executor=multiprocess_executor,
    # IOManager key remains `zarr_io` for both backends — the asset's
    # io_manager_key doesn't care which storage shim it gets.
    resources={"zarr_io": _select_io_manager()},
)
