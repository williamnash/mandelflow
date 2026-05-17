"""Stage 08: single cloud-VM multi-frame zoom CLI.

Runs s07's loop shape with two adjustments for cloud / parallelism:

  1. `--output` can be a `gs://bucket/path.zarr` URL. xarray + zarr +
     gcsfs handle that transparently; `common/store.py` doesn't need to
     know which backend it's hitting.
  2. No GL context is acquired. Compute imports s04 (s03 kernel + Dask
     intra-frame tile fanout). A `LocalCluster` set up here lets the
     active scheduler use all available CPU cores — without it, dask
     would fall back to synchronous (single-threaded) execution.

End-to-end run inside the VM container:

    docker run \\
      us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev \\
      python -m stages.s08_zoom_cloud_cpu.run \\
        --n-frames 60 --resolution 480 --max-iter 256 \\
        --output gs://mandelflow-2026-zarr/runs/dev.zarr

The VM's attached service account provides GCS write access via the
metadata server. No JSON keys, no auth setup inside the container.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dask.distributed import Client, LocalCluster

from common.schedule import canonical_schedule
from common.store import create_iterations_dataset, write_frame
from stages.s08_zoom_cloud_cpu.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 08: single-VM cloud zoom")
    parser.add_argument("--n-frames", type=int, default=60)
    parser.add_argument("--resolution", type=int, default=480)
    parser.add_argument("--max-iter", type=int, default=256)
    parser.add_argument(
        "--center-re",
        type=float,
        default=None,
        help="Zoom centre, real part. Default = common.schedule.ZOOM_CENTER (-0.7435). "
             "For deep zoom (final_width < ~1e-4), pick a precise boundary point such "
             "as -0.743643887037151 to avoid landing in iteration plateaus.",
    )
    parser.add_argument(
        "--center-im",
        type=float,
        default=None,
        help="Zoom centre, imag part. Default = common.schedule.ZOOM_CENTER (0.1314). "
             "Deep-zoom partner of --center-re — e.g. 0.131825904205330 for Seahorse.",
    )
    parser.add_argument(
        "--initial-width",
        type=float,
        default=None,
        help="Initial (wide) view width. Default = common.schedule.INITIAL_WIDTH (3.5).",
    )
    parser.add_argument(
        "--final-width",
        type=float,
        default=None,
        help="Final (deep) zoom width. Default = common.schedule.FINAL_WIDTH (1e-3, "
             "float32-safe). CPU kernel is float64; safe down to ~1e-10 at 720+ resolution.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="gs://mandelflow-2026-zarr/runs/dev.zarr",
        help="Zarr store path. Use `gs://bucket/path.zarr` for GCS, "
             "or a local path for plumbing tests.",
    )
    parser.add_argument(
        "--n-workers",
        type=int,
        default=0,
        help="Dask worker processes. 0 (default) lets Dask pick based on CPU count.",
    )
    parser.add_argument(
        "--n-tiles",
        type=int,
        default=4,
        help="Tiles per side for intra-frame fanout (so n_tiles**2 tasks per frame).",
    )
    args = parser.parse_args(argv)

    # Only create parent dirs for local paths; gs:// has no concept of dirs.
    if not args.output.startswith("gs://"):
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # Pass overrides only when explicitly set, so defaults stay centralised.
    schedule_kwargs = {}
    if args.initial_width is not None:
        schedule_kwargs["initial_width"] = args.initial_width
    if args.final_width is not None:
        schedule_kwargs["final_width"] = args.final_width
    if args.center_re is not None or args.center_im is not None:
        from common.schedule import ZOOM_CENTER
        schedule_kwargs["center"] = (
            args.center_re if args.center_re is not None else ZOOM_CENTER[0],
            args.center_im if args.center_im is not None else ZOOM_CENTER[1],
        )
    cr, ci, w = canonical_schedule(args.n_frames, **schedule_kwargs)

    cluster_kwargs = {
        "threads_per_worker": 1,
        "processes": True,
        "dashboard_address": None,
    }
    if args.n_workers > 0:
        cluster_kwargs["n_workers"] = args.n_workers
    # else: let Dask default to ~one worker per CPU

    print(
        f"stage 08 zoom_cloud (CPU, s04 kernel via Dask): "
        f"n_frames={args.n_frames} resolution={args.resolution} "
        f"max_iter={args.max_iter} n_tiles={args.n_tiles}",
        flush=True,
    )
    print(f"  output: {args.output}", flush=True)
    print(f"  zoom: width {w[0]:.3g} → {w[-1]:.3g}", flush=True)

    create_iterations_dataset(
        args.output, n_frames=args.n_frames, resolution=args.resolution
    )

    with LocalCluster(**cluster_kwargs) as cluster, Client(cluster) as client:
        print(
            f"  dask: {len(client.scheduler_info()['workers'])} workers, "
            f"{os.cpu_count()} cpus",
            flush=True,
        )

        start = time.perf_counter()
        for k in range(args.n_frames):
            frame_start = time.perf_counter()
            iterations = compute_frame(
                float(cr[k]), float(ci[k]), float(w[k]),
                args.resolution, args.max_iter,
                n_tiles=args.n_tiles,
            )
            write_frame(
                args.output, frame_index=k, iterations=iterations,
                center_re=float(cr[k]), center_im=float(ci[k]), width=float(w[k]),
            )
            if k == 0 or (k + 1) % 10 == 0 or k == args.n_frames - 1:
                print(
                    f"  frame {k + 1}/{args.n_frames} "
                    f"({time.perf_counter() - frame_start:.2f}s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - start

    print(
        f"  done — {args.n_frames} frames in {elapsed:.2f}s "
        f"({elapsed * 1000 / args.n_frames:.1f} ms/frame)",
        flush=True,
    )


if __name__ == "__main__":
    main()
