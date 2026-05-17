"""Stage 00: naive Mandelbrot CLI.

Run via `uv run python -m stages.s00_naive.run`. Writes a single-frame
`(1, H, W)` Zarr to the path given by --output.

This stage is deliberately slow — at 256x256 a full render takes
seconds; at 1024x1024 it takes minutes. That cost is the baseline
later stages improve on.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from common.store import create_iterations_dataset, write_frame
from stages.s00_naive.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 00: naive Mandelbrot")
    parser.add_argument("--center-re", type=float, default=-0.75)
    parser.add_argument("--center-im", type=float, default=0.0)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--max-iter", type=int, default=256)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/s00_naive.zarr"),
        help="Zarr store path (single-frame, will be overwritten if it exists).",
    )
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"stage 00 naive: center=({args.center_re}, {args.center_im}) "
        f"width={args.width} resolution={args.resolution} max_iter={args.max_iter}"
    )
    print(f"  output: {args.output}")

    start = time.perf_counter()
    iterations = compute_frame(
        args.center_re,
        args.center_im,
        args.width,
        args.resolution,
        args.max_iter,
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
