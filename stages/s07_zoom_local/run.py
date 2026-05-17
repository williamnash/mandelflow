"""Stage 07: local multi-frame zoom Mandelbrot CLI.

Builds the canonical zoom schedule, acquires one GL context, and
loops s06's kernel across every frame. The output is a single
`(N, H, W)` Zarr — the first multi-frame artifact in the repo.

This stage is intentionally *not* using Dask. On a single laptop with
one GPU there is no parallelism win from fanning frames across
workers — the GPU can only execute one job at a time. Distributed
fan-out earns its keep at s08, where the cluster makes the difference.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from common.schedule import canonical_schedule
from common.store import create_iterations_dataset, write_frame
from render.gl_context import has_gl, make_offscreen_context
from stages.s07_zoom_local.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 07: local multi-frame zoom")
    parser.add_argument("--n-frames", type=int, default=200)
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--max-iter", type=int, default=512)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/s07_zoom_local.zarr"),
        help="Multi-frame Zarr store path (will be overwritten if it exists).",
    )
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if not has_gl():
        print(
            "Stage 07 requires an OpenGL 4.1 context (uses s06's shader). "
            "Install `uv sync --extra gpu` and ensure GL drivers are reachable.",
            file=sys.stderr,
        )
        sys.exit(1)

    cr, ci, w = canonical_schedule(args.n_frames)

    print(
        f"stage 07 zoom_local: n_frames={args.n_frames} "
        f"resolution={args.resolution} max_iter={args.max_iter}"
    )
    print(f"  zoom: width {w[0]:.3g} → {w[-1]:.3g}")
    print(f"  output: {args.output}")

    create_iterations_dataset(args.output, n_frames=args.n_frames, resolution=args.resolution)

    ctx = make_offscreen_context(1, 1)
    try:
        start = time.perf_counter()
        for k in range(args.n_frames):
            iterations = compute_frame(
                float(cr[k]), float(ci[k]), float(w[k]),
                args.resolution, args.max_iter,
                ctx=ctx,
            )
            write_frame(
                args.output, frame_index=k, iterations=iterations,
                center_re=float(cr[k]), center_im=float(ci[k]), width=float(w[k]),
            )
        elapsed = time.perf_counter() - start
    finally:
        ctx.release()
        if sys.platform == "darwin":
            import pygame
            pygame.display.quit()

    print(f"  {args.n_frames} frames in {elapsed:.2f}s "
          f"({elapsed * 1000 / args.n_frames:.1f} ms/frame)")
    print("  written")


if __name__ == "__main__":
    main()
