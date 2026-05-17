"""Stage 09: Cloud Run Jobs CPU fanout.

Two modes, auto-detected from the environment:

  - **task** — runs inside one Cloud Run Job task. Reads
    `CLOUD_RUN_TASK_INDEX` + `CLOUD_RUN_TASK_COUNT` from env, computes
    its slice of the frame schedule, writes each frame as one
    icechunk commit. Parameters (n_frames, output, etc.) come from
    `MANDELFLOW_*` env vars injected by the dispatcher.

  - **dispatch** — runs locally on your laptop or in CI. Initialises
    the icechunk repo + schema at the target URL, then invokes
    `gcloud run jobs execute` to spawn N parallel tasks. Waits for
    completion. No frames computed on the dispatch host.

Mode is selected by presence of `CLOUD_RUN_TASK_INDEX` (set by the
Cloud Run runtime in every task). When that's absent, we assume
you're dispatching.

Prereqs (one-time, see stages/s09_zoom_fanout_cpu/README.md):

  - Cloud Run Job `mandelflow-zoom` must exist in the project. Create
    via `gcloud run jobs create` (see README) or via the Terraform
    in `terraform/`.
  - The container image (built by `gcloud builds submit --config
    cloudbuild.yaml`) must be in Artifact Registry.
  - The Job's runtime service account needs
    `roles/storage.objectAdmin` on the output bucket (same SA as
    `mandelflow-vm` from s08 if you reuse it).

Local validation (no cloud):

  CLOUD_RUN_TASK_INDEX=0 CLOUD_RUN_TASK_COUNT=4 \\
  MANDELFLOW_N_FRAMES=20 MANDELFLOW_OUTPUT=out/s09_test.icechunk \\
  MANDELFLOW_RESOLUTION=240 MANDELFLOW_MAX_ITER=256 \\
  uv run python -m stages.s09_zoom_fanout_cpu.run

  Then bump CLOUD_RUN_TASK_INDEX to 1, 2, 3 to validate each task's
  frame range writes correctly. All four together produce the full
  20-frame icechunk repo.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from math import ceil
from pathlib import Path

import numpy as np
import xarray as xr

from common.schedule import canonical_schedule
from common.store import ITERATIONS_DTYPE
from stages.s09_zoom_fanout_cpu.compute import compute_frame

DEFAULT_OUTPUT = "gs://mandelflow-2026-zarr/runs/s09.icechunk"
DEFAULT_JOB_NAME = "mandelflow-zoom"
DEFAULT_REGION = "us-central1"


def _open_repo(path: str):
    """Open or create an icechunk repo at the given path (local FS or gs://)."""
    import icechunk
    if path.startswith("gs://"):
        parts = path[5:].split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""
        storage = icechunk.gcs_storage(bucket=bucket, prefix=prefix)
    else:
        Path(path).mkdir(parents=True, exist_ok=True)
        storage = icechunk.local_filesystem_storage(path)
    return icechunk.Repository.open_or_create(storage)


def _init_schema(repo, n_frames: int, resolution: int) -> None:
    """Idempotent: write the dataset schema if `iterations` is missing."""
    try:
        session = repo.readonly_session("main")
        ds = xr.open_zarr(session.store)
        if "iterations" in ds.data_vars:
            return
    except Exception:
        pass

    iterations = np.zeros(
        (n_frames, resolution, resolution), dtype=ITERATIONS_DTYPE
    )
    ds = xr.Dataset(
        data_vars={"iterations": (("frame", "y", "x"), iterations)},
        coords={
            "frame": np.arange(n_frames, dtype=np.int32),
            "center_re": ("frame", np.full(n_frames, np.nan)),
            "center_im": ("frame", np.full(n_frames, np.nan)),
            "width": ("frame", np.full(n_frames, np.nan)),
        },
    )
    encoding = {"iterations": {"chunks": (1, resolution, resolution)}}
    session = repo.writable_session("main")
    ds.to_zarr(session.store, mode="w", encoding=encoding, zarr_format=3)
    session.commit("initialize iterations dataset schema")


def _write_frame(repo, k: int, iterations: np.ndarray,
                 cr: float, ci: float, w: float) -> str:
    """Write one frame as one icechunk commit. Returns the snapshot ID."""
    ds_frame = xr.Dataset(
        data_vars={
            "iterations": (
                ("frame", "y", "x"),
                iterations.astype(ITERATIONS_DTYPE)[None, :, :],
            )
        },
        coords={
            "frame": np.array([k], dtype=np.int32),
            "center_re": ("frame", np.array([cr])),
            "center_im": ("frame", np.array([ci])),
            "width": ("frame", np.array([w])),
        },
    )
    session = repo.writable_session("main")
    ds_frame.to_zarr(session.store, region={"frame": slice(k, k + 1)})
    return session.commit(f"frame {k:04d}")


def run_task() -> None:
    """Per-task entrypoint, invoked inside each Cloud Run Job task."""
    task_index = int(os.environ["CLOUD_RUN_TASK_INDEX"])
    task_count = int(os.environ["CLOUD_RUN_TASK_COUNT"])
    output = os.environ.get("MANDELFLOW_OUTPUT", DEFAULT_OUTPUT)
    n_frames = int(os.environ.get("MANDELFLOW_N_FRAMES", "120"))
    resolution = int(os.environ.get("MANDELFLOW_RESOLUTION", "720"))
    max_iter = int(os.environ.get("MANDELFLOW_MAX_ITER", "512"))

    # Even split with remainder absorbed by the last task.
    frames_per_task = ceil(n_frames / task_count)
    start = task_index * frames_per_task
    end = min(start + frames_per_task, n_frames)

    print(
        f"task {task_index}/{task_count}: frames [{start}..{end}) "
        f"({end - start} frames, resolution={resolution}, max_iter={max_iter})",
        flush=True,
    )
    print(f"  output: {output}", flush=True)

    repo = _open_repo(output)
    # Defensive: in cloud, the dispatcher initialises the schema before
    # fanning out, so this no-ops via the idempotent check. For local
    # validation (running tasks one at a time without a dispatcher),
    # the first task creates the schema.
    _init_schema(repo, n_frames, resolution)
    cr, ci, w = canonical_schedule(n_frames)

    t_start = time.perf_counter()
    for k in range(start, end):
        t_frame = time.perf_counter()
        iters = compute_frame(
            float(cr[k]), float(ci[k]), float(w[k]),
            resolution, max_iter,
        )
        commit = _write_frame(
            repo, k, iters,
            float(cr[k]), float(ci[k]), float(w[k]),
        )
        commit_short = commit[:8] if isinstance(commit, str) else str(commit)[:8]
        print(
            f"  task {task_index}: frame {k:04d} "
            f"({time.perf_counter() - t_frame:.2f}s, commit {commit_short})",
            flush=True,
        )
    elapsed = time.perf_counter() - t_start
    print(
        f"task {task_index}/{task_count}: done — {end - start} frames in "
        f"{elapsed:.1f}s ({elapsed * 1000 / max(end - start, 1):.0f} ms/frame)",
        flush=True,
    )


def run_dispatch(argv: list[str] | None) -> None:
    """Control-host dispatcher: init repo, submit Cloud Run Job execution."""
    parser = argparse.ArgumentParser(description="Stage 09: Cloud Run Jobs CPU fanout")
    parser.add_argument("--n-frames", type=int, default=120)
    parser.add_argument("--n-tasks", type=int, default=8,
                        help="Cloud Run Job task / parallelism count.")
    parser.add_argument("--resolution", type=int, default=720)
    parser.add_argument("--max-iter", type=int, default=512)
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT)
    parser.add_argument("--job-name", type=str, default=DEFAULT_JOB_NAME)
    parser.add_argument("--region", type=str, default=DEFAULT_REGION)
    args = parser.parse_args(argv)

    print(
        f"stage 09 zoom_fanout_cpu (dispatch): "
        f"{args.n_frames} frames across {args.n_tasks} tasks "
        f"({ceil(args.n_frames / args.n_tasks)} frames/task)",
        flush=True,
    )
    print(f"  output: {args.output}", flush=True)
    print(f"  cloud run job: {args.job_name} ({args.region})", flush=True)

    # Init the icechunk repo + schema BEFORE fanning out tasks. Concurrent
    # open_or_create from multiple processes is documented unsafe in icechunk;
    # by the time tasks call open_or_create, the repo exists and the call
    # is a no-op.
    print("  initialising icechunk repo + schema...", flush=True)
    repo = _open_repo(args.output)
    _init_schema(repo, args.n_frames, args.resolution)
    print("  ✓ repo ready", flush=True)

    cmd = [
        "gcloud", "run", "jobs", "execute", args.job_name,
        "--region", args.region,
        "--tasks", str(args.n_tasks),
        "--parallelism", str(args.n_tasks),
        "--wait",
        "--update-env-vars",
        (
            f"MANDELFLOW_N_FRAMES={args.n_frames},"
            f"MANDELFLOW_OUTPUT={args.output},"
            f"MANDELFLOW_RESOLUTION={args.resolution},"
            f"MANDELFLOW_MAX_ITER={args.max_iter}"
        ),
    ]
    print(f"  → {' '.join(cmd)}", flush=True)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, check=False)
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        print(
            f"Cloud Run Job execution failed (exit code {result.returncode}) "
            f"after {elapsed:.1f}s",
            file=sys.stderr,
        )
        sys.exit(result.returncode)
    print(f"  ✓ all tasks complete in {elapsed:.1f}s", flush=True)


def main(argv: list[str] | None = None) -> None:
    # Cloud Run Jobs sets CLOUD_RUN_TASK_INDEX in every task instance.
    # Its presence tells us we're running inside the cloud, not locally.
    if "CLOUD_RUN_TASK_INDEX" in os.environ:
        run_task()
    else:
        run_dispatch(argv)


if __name__ == "__main__":
    main()
