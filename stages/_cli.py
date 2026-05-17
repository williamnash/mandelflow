"""Shared CLI plumbing for single-frame Mandelbrot stages.

Stages 00-06 all share the same shape: parse the canonical Mandelbrot
arguments, call the stage's `compute_frame`, write a 1-frame Zarr at
the canonical schema. The only per-stage differences are the label,
the default output path, and which `compute_frame` to call.

Stages 07+ (zoom across many frames) and 09 (FastAPI viewer) do not
use this helper — their shape is different enough that hooks here
would obscure rather than clarify.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable

import numpy as np

from common.store import create_iterations_dataset, write_frame

ComputeFrame = Callable[[float, float, float, int, int], np.ndarray]


def run_single_frame_stage(
    stage_id: str,
    stage_label: str,
    compute_frame: ComputeFrame,
    default_output: Path,
    argv: list[str] | None = None,
) -> None:
    parser = argparse.ArgumentParser(
        description=f"Stage {stage_id}: {stage_label}"
    )
    parser.add_argument("--center-re", type=float, default=-0.75)
    parser.add_argument("--center-im", type=float, default=0.0)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--max-iter", type=int, default=256)
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help="Zarr store path (single-frame, will be overwritten if it exists).",
    )
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"stage {stage_id} {stage_label}: "
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
