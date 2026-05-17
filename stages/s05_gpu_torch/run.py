"""Stage 05: PyTorch GPU Mandelbrot CLI.

Bespoke (like s04) — needs to acquire the GPU device upfront with a
clear error message if none is available, before any compute work
begins. Per the reproducibility contract: never a stack trace.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from common.store import create_iterations_dataset, write_frame
from render.torch_device import get_torch_device
from stages.s05_gpu_torch.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 05: PyTorch GPU Mandelbrot")
    parser.add_argument("--center-re", type=float, default=-0.75)
    parser.add_argument("--center-im", type=float, default=0.0)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--max-iter", type=int, default=256)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/s05_gpu_torch.zarr"),
        help="Zarr store path (single-frame, will be overwritten if it exists).",
    )
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    try:
        device = get_torch_device()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(
        f"stage 05 gpu_torch: "
        f"center=({args.center_re}, {args.center_im}) "
        f"width={args.width} resolution={args.resolution} max_iter={args.max_iter}"
    )
    print(f"  device: {device}")
    print(f"  output: {args.output}")

    start = time.perf_counter()
    iterations = compute_frame(
        args.center_re,
        args.center_im,
        args.width,
        args.resolution,
        args.max_iter,
        device=device,
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
