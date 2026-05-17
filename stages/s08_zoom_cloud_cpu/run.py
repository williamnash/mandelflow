"""Stage 08: single cloud-VM multi-frame zoom CLI.

Runs s07's loop shape with two adjustments for cloud:

  1. `--output` can be a `gs://bucket/path.zarr` URL. xarray + zarr +
     gcsfs handle that transparently; `common/store.py` doesn't need to
     know which backend it's hitting.
  2. No GL context is acquired — the compute kernel imported from
     `stages.s08_zoom_cloud_cpu.compute` is currently s03 (CPU numba),
     not s06 (GPU shader), pending GPU quota approval.

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
import sys
import time
from pathlib import Path

from common.schedule import canonical_schedule
from common.store import create_iterations_dataset, write_frame
from stages.s08_zoom_cloud_cpu.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 08: single-VM cloud zoom")
    parser.add_argument("--n-frames", type=int, default=60)
    parser.add_argument("--resolution", type=int, default=480)
    parser.add_argument("--max-iter", type=int, default=256)
    parser.add_argument(
        "--output",
        type=str,
        default="gs://mandelflow-2026-zarr/runs/dev.zarr",
        help="Zarr store path. Use `gs://bucket/path.zarr` for GCS, "
             "or a local path for plumbing tests.",
    )
    args = parser.parse_args(argv)

    # Only create parent dirs for local paths; gs:// has no concept of dirs.
    if not args.output.startswith("gs://"):
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    cr, ci, w = canonical_schedule(args.n_frames)

    print(
        f"stage 08 zoom_cloud (CPU, s03 kernel): "
        f"n_frames={args.n_frames} resolution={args.resolution} "
        f"max_iter={args.max_iter}",
        flush=True,
    )
    print(f"  output: {args.output}", flush=True)
    print(f"  zoom: width {w[0]:.3g} → {w[-1]:.3g}", flush=True)

    create_iterations_dataset(
        args.output, n_frames=args.n_frames, resolution=args.resolution
    )

    start = time.perf_counter()
    for k in range(args.n_frames):
        frame_start = time.perf_counter()
        iterations = compute_frame(
            float(cr[k]), float(ci[k]), float(w[k]),
            args.resolution, args.max_iter,
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
