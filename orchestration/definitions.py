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
from common.store import create_iterations_dataset, write_frame
from stages.s07_zoom_local.compute import compute_frame

# Configuration. Bump these to do a bigger run; partition count is fixed
# at module load time, so changing N_FRAMES means restarting `dagster dev`.
N_FRAMES = 120
RESOLUTION = 720
MAX_ITER = 1024
ZARR_PATH = "out/dagster_run.zarr"


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
    resources={
        "zarr_io": ZarrFrameIOManager(
            path=ZARR_PATH,
            n_frames=N_FRAMES,
            resolution=RESOLUTION,
        ),
    },
)
