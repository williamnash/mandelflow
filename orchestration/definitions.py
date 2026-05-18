"""Dagster orchestration for mandelflow.

One `iterations` asset, partitioned **by Pod** (worker), where each Pod
computes a contiguous range of frames and writes them to a shared Zarr or
icechunk store. Workload shape is driven by `common.config.RunConfig`,
selected via `MANDELFLOW_PRESET` (demo / portfolio / showcase) plus any
`MANDELFLOW_*` overrides.

Three switchable dimensions selected at module load time via env vars:

| Env var                  | Values                                          | Effect                                  |
|--------------------------|-------------------------------------------------|-----------------------------------------|
| `MANDELFLOW_KERNEL`      | `gpu_shader` (default), `numba_cpu`, `dask_cpu` | which compute_frame the asset calls     |
| `MANDELFLOW_STORAGE`     | `zarr` (default), `icechunk`                    | which IOManager writes the partitions   |
| `MANDELFLOW_EXECUTOR`    | `multiprocess` (default), `k8s_cpu`, `k8s_gpu`  | how Pods run                            |

Sensible combinations:

  Laptop dev (default):    multiprocess + gpu_shader + zarr      + preset=demo
  Stage 09 (CPU on GKE):   k8s_cpu      + numba_cpu  + icechunk  + preset=showcase
  Stage 11 (GPU on GKE):   k8s_gpu      + gpu_shader + icechunk  + preset=showcase

The k8s executor propagates `MANDELFLOW_*` env vars into each Pod so the
Pod re-loads this module with the right kernel / storage / preset. Local
Dagster talks to the remote cluster via `~/.kube/config`.

Architectural notes (DESIGN.md §3):
- Partitions ≡ Pods. One partition per worker; each worker handles a
  contiguous frame range. Amortises ~25s Pod-startup over a meaningful
  amount of compute. See `stages/s11_zoom_fanout_gpu/README.md` for the
  rationale (frame-range-per-Pod vs frame-per-Pod).
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

from common.config import RunConfig, describe, from_env
from common.schedule import canonical_schedule
from common.store import ITERATIONS_DTYPE, create_iterations_dataset, write_frame

# Resolve the run config at module load. The k8s executor forwards
# MANDELFLOW_* env vars so each Pod sees the same config.
CFG: RunConfig = from_env()

# Kernel selector. Driven by env so the same module config works for both
# the local laptop (default GPU shader) and the K8s case.
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

ZARR_PATH = os.environ.get("MANDELFLOW_ZARR_PATH", "out/dagster_run.zarr")
ICECHUNK_PATH = os.environ.get(
    "MANDELFLOW_ICECHUNK_PATH", "out/dagster_run.icechunk"
)


pod_partitions = StaticPartitionsDefinition(
    [f"{i:04d}" for i in range(CFG.n_pods)]
)


def _frame_range_for_pod(pod_idx: int, cfg: RunConfig = CFG) -> tuple[int, int]:
    """Inclusive-exclusive frame range owned by `pod_idx`.

    Frames are distributed as evenly as possible across `cfg.n_pods` Pods;
    the last few Pods may pick up one extra frame each when `n_frames`
    doesn't divide. Same arithmetic as `numpy.array_split`.
    """
    n_frames = cfg.n_frames
    n_pods = cfg.n_pods
    base, rem = divmod(n_frames, n_pods)
    start = pod_idx * base + min(pod_idx, rem)
    end = start + base + (1 if pod_idx < rem else 0)
    return start, end


class ZarrFrameIOManager(ConfigurableIOManager):
    """Persist a Pod's `dict[frame_idx → array]` output into a shared Zarr.

    Initialises the Zarr store on first write — region-write semantics
    plus per-frame chunks means concurrent Pods writing disjoint frames
    don't contend. Same code works for local paths (`out/foo.zarr`) and
    `gs://bucket/foo.zarr` (xarray + gcsfs).

    The schema-init race between concurrent Pods on the very first run
    is mitigated by the existence check; for safety in true distributed
    settings, pre-init the store with `create_iterations_dataset` before
    the run.
    """

    path: str
    n_frames: int
    resolution: int

    def _ensure_dataset(self) -> None:
        is_gcs = self.path.startswith("gs://")
        if not is_gcs and Path(self.path).exists():
            return
        create_iterations_dataset(self.path, self.n_frames, self.resolution)

    def handle_output(self, context: OutputContext, obj: dict[int, np.ndarray]) -> None:
        self._ensure_dataset()
        cr, ci, w = canonical_schedule(
            self.n_frames, CFG.initial_width, CFG.final_width
        )
        for k in sorted(obj):
            write_frame(
                self.path,
                frame_index=k,
                iterations=obj[k],
                center_re=float(cr[k]),
                center_im=float(ci[k]),
                width=float(w[k]),
            )
        context.log.info(
            f"zarr: wrote {len(obj)} frames [{min(obj)}..{max(obj)}] "
            f"to {self.path}"
        )

    def load_input(self, context: InputContext) -> dict[int, np.ndarray]:
        raise NotImplementedError(
            "ZarrFrameIOManager.load_input not needed — read the store "
            "directly with xarray.open_zarr() for downstream consumption."
        )


class IcechunkFrameIOManager(ConfigurableIOManager):
    """Persist a Pod's frames as one icechunk commit.

    Each materialised partition (= one Pod) opens a writable session,
    writes its frame range via region-writes, and commits once. The
    commit message names the frame range, so the icechunk commit log
    becomes Pod-level data lineage that maps 1:1 onto Dagster's
    partition-materialisation events.

    Works for local filesystem paths and `gs://bucket/prefix` URLs. For
    S3 / Azure / R2 / Tigris, swap the storage backend in `_open_repo`.

    Concurrent writers: icechunk's transactional commits handle the
    parallel-write semantics. Different Pods writing disjoint frame
    ranges = disjoint chunks; sessions merge automatically. The one
    concern is `Repository.open_or_create` racing on the very first
    write — for cloud runs, pre-initialise the repo manually (or with
    a tiny upstream asset) before kicking off the fan-out.
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
        """Initialise the dataset schema if the repo is empty. Idempotent."""
        try:
            session = repo.readonly_session("main")
            ds = xr.open_zarr(session.store)
            if "iterations" in ds.data_vars:
                return
        except Exception:
            pass

        iterations = np.zeros(
            (self.n_frames, self.resolution, self.resolution),
            dtype=ITERATIONS_DTYPE,
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

    def handle_output(self, context: OutputContext, obj: dict[int, np.ndarray]) -> None:
        repo = self._open_repo()
        self._ensure_schema(repo)

        cr, ci, w = canonical_schedule(
            self.n_frames, CFG.initial_width, CFG.final_width
        )
        frames = sorted(obj)
        session = repo.writable_session("main")
        for k in frames:
            ds_frame = xr.Dataset(
                data_vars={
                    "iterations": (
                        ("frame", "y", "x"),
                        obj[k].astype(ITERATIONS_DTYPE)[None, :, :],
                    )
                },
                coords={
                    "frame": np.array([k], dtype=np.int32),
                    "center_re": ("frame", np.array([float(cr[k])])),
                    "center_im": ("frame", np.array([float(ci[k])])),
                    "width": ("frame", np.array([float(w[k])])),
                },
            )
            ds_frame.to_zarr(session.store, region={"frame": slice(k, k + 1)})

        snapshot = session.commit(
            f"pod {context.partition_key}: frames {frames[0]:04d}..{frames[-1]:04d}"
        )
        context.log.info(
            f"icechunk: pod {context.partition_key} wrote {len(frames)} "
            f"frames [{frames[0]}..{frames[-1]}]; commit "
            f"{snapshot[:8] if isinstance(snapshot, str) else snapshot}"
        )

    def load_input(self, context: InputContext) -> dict[int, np.ndarray]:
        raise NotImplementedError(
            "IcechunkFrameIOManager.load_input not needed — read the repo "
            "directly with xarray.open_zarr(repo.readonly_session('main').store)."
        )


def _k8s_executor(*, gpu: bool):
    """Build a k8s_job_executor configured for our compute Pods.

    `gpu=False` (s09 architecture): plain CPU Pods. CPU node pool default
    selectors apply. Each Pod gets 2 vCPU / 4 GiB.

    `gpu=True` (s11 architecture): adds the nvidia.com/gpu toleration so
    Pods schedule onto the tainted GPU node pool, plus a GPU resource
    limit so the device plugin makes one T4 available to the container.

    Forwards MANDELFLOW_* env so each Pod re-loads this module with the
    same kernel / storage / preset selection.
    """
    from dagster_k8s import k8s_job_executor

    image = os.environ.get(
        "MANDELFLOW_IMAGE",
        "us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev",
    )
    sa = os.environ.get("MANDELFLOW_K8S_SA", "compute-sa")

    forwarded = {}
    for key in (
        "MANDELFLOW_KERNEL", "MANDELFLOW_STORAGE",
        "MANDELFLOW_ICECHUNK_PATH", "MANDELFLOW_ZARR_PATH",
        "MANDELFLOW_IMAGE", "MANDELFLOW_PRESET",
        "MANDELFLOW_N_FRAMES", "MANDELFLOW_RESOLUTION",
        "MANDELFLOW_INITIAL_WIDTH", "MANDELFLOW_FINAL_WIDTH",
        "MANDELFLOW_FPS", "MANDELFLOW_N_PODS", "MANDELFLOW_MAX_ITER",
    ):
        if key in os.environ:
            forwarded[key] = os.environ[key]
    env_vars = [f"{k}={v}" for k, v in forwarded.items()]

    # Pod-partitioning means each Pod does substantial work; cap concurrency
    # at n_pods so we don't oversubscribe the node pool.
    config = {
        "job_image": image,
        "image_pull_policy": "Always",
        "service_account_name": sa,
        "env_vars": env_vars,
        "max_concurrent": CFG.n_pods,
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
    storage = os.environ.get("MANDELFLOW_STORAGE", "zarr").lower()
    if storage == "icechunk":
        return IcechunkFrameIOManager(
            path=ICECHUNK_PATH, n_frames=CFG.n_frames, resolution=CFG.resolution,
        )
    return ZarrFrameIOManager(
        path=ZARR_PATH, n_frames=CFG.n_frames, resolution=CFG.resolution,
    )


@asset(partitions_def=pod_partitions, io_manager_key="zarr_io")
def iterations(context) -> dict[int, np.ndarray]:
    """One Pod's contiguous range of frames.

    Partition key is the Pod index; the Pod owns a contiguous frame range
    computed via `_frame_range_for_pod`. Frames are computed sequentially
    within the Pod (sharing kernel state — e.g. one GL context across all
    frames for the GPU kernel), and returned as a dict the IOManager
    writes to storage.
    """
    pod_idx = int(context.partition_key)
    start, end = _frame_range_for_pod(pod_idx)
    cr, ci, w = canonical_schedule(CFG.n_frames, CFG.initial_width, CFG.final_width)
    context.log.info(
        f"pod {pod_idx}/{CFG.n_pods}: frames [{start}..{end}) — "
        f"{describe(CFG)}"
    )
    out: dict[int, np.ndarray] = {}
    for k in range(start, end):
        out[k] = compute_frame(
            float(cr[k]), float(ci[k]), float(w[k]),
            CFG.resolution, CFG.max_iter,
        )
    return out


defs = Definitions(
    assets=[iterations],
    executor=_select_executor(),
    resources={"zarr_io": _select_io_manager()},
)
