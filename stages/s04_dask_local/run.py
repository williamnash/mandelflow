"""Stage 04: Dask local-cluster Mandelbrot CLI.

First stage that needs setup outside `compute_frame` — a Dask
`LocalCluster` of N worker *processes* is started before the kernel
runs and torn down after. Tiles fan across those workers via the
active Dask scheduler.

This is intentionally not built on top of `stages._cli.run_single_frame_stage`
— the cluster lifecycle is enough divergence from the s00–s03 template
that hooks would obscure rather than clarify. If s05 / s06 want a
similar setup-then-compute shape (GPU device acquisition, GL context),
we'll lift a hook into _cli.py at that point with two real examples to
inform the design.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from dask.distributed import Client, LocalCluster

from common.store import create_iterations_dataset, write_frame
from stages.s04_dask_local.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 04: Dask local-cluster Mandelbrot")
    parser.add_argument("--center-re", type=float, default=-0.75)
    parser.add_argument("--center-im", type=float, default=0.0)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--max-iter", type=int, default=256)
    parser.add_argument("--n-tiles", type=int, default=4,
                        help="Per-side tile count; image fans into n_tiles**2 blocks.")
    parser.add_argument("--n-workers", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/s04_dask_local.zarr"),
        help="Zarr store path (single-frame, will be overwritten if it exists).",
    )
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"stage 04 dask_local: "
        f"center=({args.center_re}, {args.center_im}) "
        f"width={args.width} resolution={args.resolution} max_iter={args.max_iter} "
        f"n_tiles={args.n_tiles} n_workers={args.n_workers}"
    )
    print(f"  output: {args.output}")

    with LocalCluster(
        n_workers=args.n_workers,
        threads_per_worker=1,
        processes=True,
        dashboard_address=None,
    ) as cluster, Client(cluster):
        start = time.perf_counter()
        iterations = compute_frame(
            args.center_re,
            args.center_im,
            args.width,
            args.resolution,
            args.max_iter,
            n_tiles=args.n_tiles,
        )
        elapsed = time.perf_counter() - start
        print(f"  compute_frame: {elapsed:.2f}s")

    create_iterations_dataset(args.output, n_frames=1, resolution=args.resolution)
    write_frame(
        args.output,
        frame_index=0,
        iterations=iterations,
        center_re=args.center_re,
        center_im=args.center_im,
        width=args.width,
    )
    print("  written")


if __name__ == "__main__":
    main()
