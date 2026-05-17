"""Stage 06: GLSL fragment-shader Mandelbrot CLI.

Bespoke run.py (third stage to depart from the _cli.py template).
Preflights the GL context via has_gl(); fails with one clear line if
the context can't be created, matching the reproducibility contract.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from common.store import create_iterations_dataset, write_frame
from render.gl_context import has_gl
from stages.s06_gpu_shader.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 06: GLSL shader Mandelbrot")
    parser.add_argument("--center-re", type=float, default=-0.75)
    parser.add_argument("--center-im", type=float, default=0.0)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--max-iter", type=int, default=256)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/s06_gpu_shader.zarr"),
        help="Zarr store path (single-frame, will be overwritten if it exists).",
    )
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if not has_gl():
        print(
            "Stage 06 requires an OpenGL 4.1 context. "
            "Install `uv sync --extra gpu` and ensure GL drivers are reachable.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"stage 06 gpu_shader: "
        f"center=({args.center_re}, {args.center_im}) "
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
