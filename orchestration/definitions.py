"""Dagster orchestration for mandelflow.

One frame-partitioned `iterations` asset, three switchable dimensions
selected at module load time via env vars:

| Env var                  | Values                                    | Effect                                  |
|--------------------------|-------------------------------------------|-----------------------------------------|
| `MANDELFLOW_KERNEL`      | `gpu_shader` (default), `numba_cpu`, `dask_cpu` | which compute_frame the asset calls     |
| `MANDELFLOW_STORAGE`     | `zarr` (default), `icechunk`              | which IOManager writes the partitions   |
| `MANDELFLOW_EXECUTOR`    | `multiprocess` (default), `k8s_cpu`, `k8s_gpu` | how partitions run                  |

Sensible combinations:

  Laptop dev (default):    multiprocess + gpu_shader + zarr
  Stage 09 (CPU on GKE):   k8s_cpu      + numba_cpu  + icechunk (gs://)
  Stage 11 (GPU on GKE):   k8s_gpu      + gpu_shader + icechunk (gs://)

Both K8s modes share the same Dagster job code: the only differences are
node-pool tolerations and GPU resource limits in the Pod spec. The k8s
executor propagates the relevant env vars into each spawned Pod, so the
Pod re-loads this module with the right kernel/storage selected. Local
Dagster (laptop) talks to the remote cluster via `~/.kube/config`.

Local UI:

    uv run dagster dev -m orchestration.definitions
    # Opens <http://localhost:3000>; asset graph shows N_FRAMES partitions.

Architectural notes (DESIGN.md §3):
- Partitions ≡ frames. One `iterations` asset, one partition per frame.
- IOManager ≡ storage. Same asset code regardless of backend.
- Executor swap is what distinguishes local from cluster runs.
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

# Kernel selector. Driven by env so the same module config works for both
# the local laptop (default GPU shader) and the K8s case (where the Pod
# inherits MANDELFLOW_KERNEL from the executor's env_vars config).
_KERNEL = os.environ.get("MANDELFLOW_KERNEL", "gpu_shader").lower()
if _KERNEL == "gpu_shader":
    from stages.s07_zoom_local.compute import compute_frame
elif _KERNEL == "numba_cpu":
    from stages.s03_numba_opt.compute import compute_frame
elif _KERNEL == "dask_cpu":
    from stages.s04_dask_local.compute import compute_frame
else:
    raise ValueError(
        f"MANDELFLOW_KERNEL={_KERNEL!r} unrecognised. "
        f"Try: gpu_shader, numba_cpu, dask_cpu."
    )

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


def _k8s_executor(*, gpu: bool):
    """Build a k8s_job_executor configured for our compute Pods.

    `gpu=False` (s09 architecture): plain CPU Pods. CPU node pool default
    selectors apply. Each Pod gets 2 vCPU / 4 GiB.

    `gpu=True` (s11 architecture): adds the nvidia.com/gpu toleration so
    Pods schedule onto the tainted GPU node pool, plus a GPU resource
    limit so the device plugin makes one T4 available to the container.

    Both modes propagate MANDELFLOW_KERNEL / _STORAGE / _ICECHUNK_PATH
    into the Pod env so the spawned partition re-loads this module with
    the same selection state. This is what makes "same code laptop and
    cluster" actually true.

    Dagster talks to the cluster via the laptop's `~/.kube/config` (set
    up by `gcloud container clusters get-credentials …`). For in-cluster
    Dagster (e.g., a self-hosted Dagster deployment on GKE), set
    `load_incluster_config: True` instead.
    """
    from dagster_k8s import k8s_job_executor

    image = os.environ.get(
        "MANDELFLOW_IMAGE",
        "us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev",
    )
    sa = os.environ.get("MANDELFLOW_K8S_SA", "compute-sa")

    # Env vars to forward from Dagster (laptop) into every spawned Pod.
    # Only forward the ones the Pod's orchestration.definitions will read.
    forwarded = {}
    for key in (
        "MANDELFLOW_KERNEL", "MANDELFLOW_STORAGE",
        "MANDELFLOW_ICECHUNK_PATH", "MANDELFLOW_IMAGE",
    ):
        if key in os.environ:
            forwarded[key] = os.environ[key]
    env_vars = [f"{k}={v}" for k, v in forwarded.items()]

    config = {
        "job_image": image,
        "image_pull_policy": "Always",
        "service_account_name": sa,
        "env_vars": env_vars,
        "max_concurrent": 16,
    }

    if gpu:
        config["step_k8s_config"] = {
            "pod_spec_config": {
                "tolerations": [{
                    "key": "nvidia.com/gpu",
                    "operator": "Equal",
                    "value": "present",
                    "effect": "NoSchedule",
                }],
            },
            "container_config": {
                "resources": {
                    "limits": {"nvidia.com/gpu": "1", "memory": "8Gi"},
                    "requests": {"cpu": "2", "memory": "4Gi"},
                },
            },
        }
    else:
        config["step_k8s_config"] = {
            "container_config": {
                "resources": {
                    "limits": {"cpu": "2", "memory": "4Gi"},
                    "requests": {"cpu": "1", "memory": "2Gi"},
                },
            },
        }

    return k8s_job_executor.configured(config)


def _select_executor():
    """Pick the executor based on MANDELFLOW_EXECUTOR env var.

    `multiprocess` (default): local OS-process parallelism. Fine for the
    laptop demo and CI.
    `k8s_cpu`: dagster-k8s `k8s_job_executor` — one K8s Job per partition,
    no GPU toleration. The s09 architecture.
    `k8s_gpu`: same but with GPU toleration + GPU resource limit. The s11
    architecture.
    """
    mode = os.environ.get("MANDELFLOW_EXECUTOR", "multiprocess").lower()
    if mode == "multiprocess":
        return multiprocess_executor
    if mode == "k8s_cpu":
        return _k8s_executor(gpu=False)
    if mode == "k8s_gpu":
        return _k8s_executor(gpu=True)
    raise ValueError(
        f"MANDELFLOW_EXECUTOR={mode!r} unrecognised. "
        f"Try: multiprocess, k8s_cpu, k8s_gpu."
    )


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
    executor=_select_executor(),
    # IOManager key remains `zarr_io` for both backends — the asset's
    # io_manager_key doesn't care which storage shim it gets.
    resources={"zarr_io": _select_io_manager()},
)
