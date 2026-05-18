"""Stage 09: cloud CPU fan-out (Cloud Run Jobs OR Kubernetes Indexed Jobs).

Three execution modes, auto-detected from the environment:

  - **K8s task** (`JOB_COMPLETION_INDEX` set) — inside one Pod of a
    Kubernetes Indexed Job. Reads `JOB_COMPLETION_INDEX` + total tasks
    from env, computes its frame range, writes frames to the shared
    icechunk repo. This is the path the GKE CPU fan-out + s11 GPU
    fan-out both use; the only difference between CPU and GPU is the
    Job spec (`MANDELFLOW_KERNEL` env + GPU tolerations).

  - **Cloud Run task** (`CLOUD_RUN_TASK_INDEX` set) — inside one Cloud
    Run Job task. Same task body; different env-var names for the
    index. Cloud Run doesn't fit s11's GPU story (preview-grade, L4
    only), so this path is CPU-only.

  - **Dispatch** (neither set) — runs locally. Picks a target via
    `--target {gke,gke-gpu,cloudrun}`, initialises the icechunk repo
    once (avoiding the `Repository.open_or_create` race across Pods),
    submits the fan-out, waits for completion.

Workload shape comes from `common.config.RunConfig`, selected via
`MANDELFLOW_PRESET` (demo / portfolio / showcase) with individual
`MANDELFLOW_*` overrides. The dispatcher forwards every `MANDELFLOW_*`
env var into the Pods so each Pod re-loads `from_env()` and gets the
same config.

Local validation (no cloud — simulate one K8s task at a time):

    JOB_COMPLETION_INDEX=0 JOB_COMPLETIONS=4 \\
    MANDELFLOW_PRESET=demo \\
    MANDELFLOW_OUTPUT=out/s09_test.icechunk \\
    uv run python -m stages.s09_zoom_fanout_cpu.run

    # Then increment JOB_COMPLETION_INDEX to 1, 2, 3.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import xarray as xr

from common.config import RunConfig, describe, frame_range_for_pod, from_env
from common.schedule import canonical_schedule
from common.store import ITERATIONS_DTYPE

# Kernel selector. Default numba_cpu for the s09 CPU path; gke-gpu target
# in the dispatcher flips this to gpu_shader for s11 reuse. The Pod's env
# (set in the Job spec) is what actually picks the kernel here.
_KERNEL = os.environ.get("MANDELFLOW_KERNEL", "numba_cpu").lower()
if _KERNEL == "gpu_shader":
    from stages.s07_zoom_local.compute import compute_frame
elif _KERNEL == "numba_cpu":
    from stages.s03_numba_opt.compute import compute_frame
elif _KERNEL == "dask_cpu":
    from stages.s04_dask_local.compute import compute_frame
else:
    raise ValueError(
        f"MANDELFLOW_KERNEL={_KERNEL!r} unrecognised. "
        f"Try: numba_cpu, gpu_shader, dask_cpu."
    )

DEFAULT_OUTPUT = "gs://mandelflow-2026-zarr/runs/s09.icechunk"

# Cloud Run defaults
DEFAULT_CLOUDRUN_JOB = "mandelflow-zoom"
DEFAULT_REGION = "us-central1"

# K8s defaults
DEFAULT_K8S_NAMESPACE = "default"
DEFAULT_K8S_SA = "compute-sa"
DEFAULT_IMAGE = (
    "us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev"
)
K8S_JOB_TEMPLATE = (
    Path(__file__).parent / "k8s" / "job.yaml.tmpl"
)


# ─── Repo + frame writes (shared by all task modes) ─────────────────────────


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


# ─── Task body (shared by Cloud Run + K8s task modes) ───────────────────────


def run_task(task_index: int, task_count: int) -> None:
    """Compute and write this task's frame range to the shared icechunk repo.

    Same body for Cloud Run and K8s — only the env-var name for the index
    differs (handled in `main`). Each frame is written via region-write
    and the whole task's range is committed in one session at the end.
    """
    cfg: RunConfig = from_env()
    output = os.environ.get("MANDELFLOW_OUTPUT", DEFAULT_OUTPUT)

    # Frame range — same arithmetic as the Dagster asset, so a Pod and
    # a multiprocess worker compute identical slices.
    start, end = frame_range_for_pod(task_index, task_count, cfg.n_frames)

    print(
        f"task {task_index}/{task_count}: frames [{start}..{end}) "
        f"({end - start} frames, kernel={_KERNEL})",
        flush=True,
    )
    print(f"  {describe(cfg)}", flush=True)
    print(f"  output: {output}", flush=True)

    import icechunk
    repo = _open_repo(output)
    # Defensive: in cloud the dispatcher initialises the schema before
    # fan-out so this is a no-op. Local validation (running tasks one
    # at a time without a dispatcher) hits the init path on the first
    # task only.
    _init_schema(repo, cfg.n_frames, cfg.resolution)

    cr, ci, w = canonical_schedule(cfg.n_frames, cfg.initial_width, cfg.final_width)

    t_start = time.perf_counter()
    session = repo.writable_session("main")
    for k in range(start, end):
        t_frame = time.perf_counter()
        iters = compute_frame(
            float(cr[k]), float(ci[k]), float(w[k]),
            cfg.resolution, cfg.max_iter,
        )
        ds_frame = xr.Dataset(
            data_vars={
                "iterations": (
                    ("frame", "y", "x"),
                    iters.astype(ITERATIONS_DTYPE)[None, :, :],
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
        print(
            f"  task {task_index}: frame {k:04d} "
            f"({time.perf_counter() - t_frame:.2f}s)",
            flush=True,
        )
    # Concurrent commit semantics: another Pod may have advanced `main`
    # while we were computing. Disjoint region writes (each Pod owns a
    # distinct frame range = distinct chunks) are mergeable, so rebase
    # + retry resolves cleanly. Retry up to 10 times — for n_pods up to
    # ~20 this is comfortable headroom.
    commit_msg = f"task {task_index}/{task_count}: frames {start:04d}..{end - 1:04d}"
    for attempt in range(10):
        try:
            snapshot = session.commit(commit_msg)
            break
        except icechunk.ConflictError:
            if attempt == 9:
                raise
            session.rebase(icechunk.BasicConflictSolver())
            print(
                f"  task {task_index}: rebase+retry commit (attempt {attempt + 2})",
                flush=True,
            )
    commit_short = snapshot[:8] if isinstance(snapshot, str) else str(snapshot)[:8]
    elapsed = time.perf_counter() - t_start
    print(
        f"task {task_index}/{task_count}: done — {end - start} frames in "
        f"{elapsed:.1f}s ({elapsed * 1000 / max(end - start, 1):.0f} ms/frame) "
        f"commit {commit_short}",
        flush=True,
    )


# ─── Dispatchers (Cloud Run + GKE) ──────────────────────────────────────────


def _build_env_var_list() -> dict[str, str]:
    """Collect MANDELFLOW_* env vars to forward into Pods.

    Plus MANDELFLOW_OUTPUT, which is what the task code reads to find
    the icechunk repo. Plus MANDELFLOW_KERNEL so the Pod picks the
    right compute_frame import.
    """
    forwarded = {}
    for key in os.environ:
        if key.startswith("MANDELFLOW_"):
            forwarded[key] = os.environ[key]
    return forwarded


def _dispatch_cloudrun(args: argparse.Namespace, cfg: RunConfig, env_vars: dict[str, str]) -> int:
    """Submit the existing Cloud Run Job (CPU only)."""
    env_str = ",".join(f"{k}={v}" for k, v in env_vars.items())
    cmd = [
        "gcloud", "run", "jobs", "execute", args.job_name,
        "--region", args.region,
        "--tasks", str(cfg.n_pods),
        "--parallelism", str(cfg.n_pods),
        "--wait",
        "--update-env-vars", env_str,
    ]
    print(f"  → {' '.join(cmd)}", flush=True)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, check=False)
    print(f"  cloud run exit code: {result.returncode}, "
          f"elapsed {time.perf_counter() - t0:.1f}s", flush=True)
    return result.returncode


def _render_k8s_job(
    *, image: str, namespace: str, service_account: str,
    n_pods: int, gpu: bool, env_vars: dict[str, str], job_name: str,
) -> str:
    """Render the K8s Indexed Job YAML for our fan-out."""
    template = K8S_JOB_TEMPLATE.read_text()

    # Render env block. YAML list of {name, value} entries indented to fit
    # under `containers[0].env:` (8 spaces in the template).
    env_lines = []
    for k, v in env_vars.items():
        env_lines.append(f"        - name: {k}")
        env_lines.append(f"          value: \"{v}\"")
    env_block = "\n".join(env_lines) if env_lines else ""

    tolerations = ""
    gpu_limit = ""
    if gpu:
        tolerations = (
            "      tolerations:\n"
            "        - key: nvidia.com/gpu\n"
            "          operator: Equal\n"
            "          value: present\n"
            "          effect: NoSchedule"
        )
        gpu_limit = "            nvidia.com/gpu: \"1\""

    return template.format(
        JOB_NAME=job_name,
        NAMESPACE=namespace,
        N_PODS=n_pods,
        IMAGE=image,
        SERVICE_ACCOUNT=service_account,
        ENV_BLOCK=env_block,
        TOLERATIONS=tolerations,
        GPU_RESOURCE_LIMIT=gpu_limit,
    )


def _dispatch_gke(args: argparse.Namespace, cfg: RunConfig,
                  env_vars: dict[str, str], gpu: bool) -> int:
    """Render + apply a K8s Indexed Job; stream logs; report exit code."""
    # Unique job name per dispatch — re-applying with the same name on a
    # completed Job is a no-op, which can mask failures.
    job_name = f"mandelflow-{int(time.time())}"
    yaml_str = _render_k8s_job(
        image=args.image,
        namespace=args.namespace,
        service_account=args.service_account,
        n_pods=cfg.n_pods,
        gpu=gpu,
        env_vars=env_vars,
        job_name=job_name,
    )

    if args.dry_run:
        print(yaml_str)
        return 0

    print(f"  → kubectl apply (Job '{job_name}', n_pods={cfg.n_pods}, "
          f"gpu={gpu})", flush=True)
    apply = subprocess.run(
        ["kubectl", "apply", "-f", "-", "-n", args.namespace],
        input=yaml_str, text=True, check=False,
    )
    if apply.returncode != 0:
        print(f"  kubectl apply failed (exit {apply.returncode})",
              file=sys.stderr)
        return apply.returncode

    print(f"  → kubectl wait --for=condition=complete (timeout 30m)",
          flush=True)
    t0 = time.perf_counter()
    wait = subprocess.run(
        ["kubectl", "wait", "--for=condition=complete",
         f"job/{job_name}", "-n", args.namespace, "--timeout=30m"],
        check=False,
    )
    elapsed = time.perf_counter() - t0
    print(f"  kubectl wait exit code: {wait.returncode}, "
          f"elapsed {elapsed:.1f}s", flush=True)

    print(f"  → kubectl logs (combined, last 200 lines per Pod)", flush=True)
    subprocess.run(
        ["kubectl", "logs", f"job/{job_name}", "-n", args.namespace,
         "--all-containers=true", "--tail=200", "--prefix=true"],
        check=False,
    )
    return wait.returncode


def run_dispatch(argv: list[str] | None) -> None:
    """Control-host dispatcher: init repo, render Job, submit."""
    parser = argparse.ArgumentParser(
        description="Stage 09: cloud CPU/GPU fan-out dispatcher",
    )
    parser.add_argument("--target", choices=["cloudrun", "gke", "gke-gpu"],
                        default="gke",
                        help="Cloud target. Defaults to GKE CPU.")
    parser.add_argument("--output", type=str,
                        help="Icechunk path; default reads MANDELFLOW_OUTPUT "
                             "or falls back to a hardcoded GCS path.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render the Job YAML to stdout; don't submit.")

    # Cloud Run options
    parser.add_argument("--job-name", default=DEFAULT_CLOUDRUN_JOB,
                        help="(cloudrun target) Cloud Run Job name.")
    parser.add_argument("--region", default=DEFAULT_REGION,
                        help="(cloudrun target) Cloud Run region.")

    # GKE options
    parser.add_argument("--namespace", default=DEFAULT_K8S_NAMESPACE,
                        help="(gke targets) K8s namespace.")
    parser.add_argument("--service-account", default=DEFAULT_K8S_SA,
                        help="(gke targets) KSA bound to the GCP "
                             "compute SA via Workload Identity.")
    parser.add_argument("--image", default=DEFAULT_IMAGE,
                        help="(gke targets) Container image to run.")
    args = parser.parse_args(argv)

    cfg = from_env()
    output = args.output or os.environ.get("MANDELFLOW_OUTPUT", DEFAULT_OUTPUT)
    os.environ["MANDELFLOW_OUTPUT"] = output

    # gke-gpu defaults the kernel to gpu_shader so the GPU pool actually
    # does GPU work. User can override with explicit MANDELFLOW_KERNEL.
    if args.target == "gke-gpu" and "MANDELFLOW_KERNEL" not in os.environ:
        os.environ["MANDELFLOW_KERNEL"] = "gpu_shader"

    env_vars = _build_env_var_list()

    # Dispatcher info goes to stderr so --dry-run's stdout is pipeable
    # into `kubectl apply -f -`.
    log = sys.stderr
    print(f"stage 09 dispatch: target={args.target}", file=log, flush=True)
    print(f"  {describe(cfg)}", file=log, flush=True)
    print(f"  output: {output}", file=log, flush=True)
    print(f"  env vars forwarded: {sorted(env_vars)}", file=log, flush=True)

    # Init icechunk schema once on the dispatcher (avoid open_or_create race).
    if not args.dry_run:
        print("  initialising icechunk repo + schema...", file=log, flush=True)
        repo = _open_repo(output)
        _init_schema(repo, cfg.n_frames, cfg.resolution)
        print("  ✓ repo ready", file=log, flush=True)

    if args.target == "cloudrun":
        rc = _dispatch_cloudrun(args, cfg, env_vars)
    elif args.target == "gke":
        rc = _dispatch_gke(args, cfg, env_vars, gpu=False)
    elif args.target == "gke-gpu":
        rc = _dispatch_gke(args, cfg, env_vars, gpu=True)
    else:
        raise ValueError(f"unknown target: {args.target}")

    sys.exit(rc)


# ─── Entry point — mode detection ───────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Pick a mode based on which task-runtime env vars are set.

    K8s Indexed Job: sets JOB_COMPLETION_INDEX (and our Job spec sets
    JOB_COMPLETIONS so the task can derive its slice).
    Cloud Run Job: sets CLOUD_RUN_TASK_INDEX and CLOUD_RUN_TASK_COUNT.
    Neither set → we're the dispatcher.
    """
    if "JOB_COMPLETION_INDEX" in os.environ:
        run_task(
            int(os.environ["JOB_COMPLETION_INDEX"]),
            int(os.environ["JOB_COMPLETIONS"]),
        )
    elif "CLOUD_RUN_TASK_INDEX" in os.environ:
        run_task(
            int(os.environ["CLOUD_RUN_TASK_INDEX"]),
            int(os.environ["CLOUD_RUN_TASK_COUNT"]),
        )
    else:
        run_dispatch(argv)


if __name__ == "__main__":
    main()
