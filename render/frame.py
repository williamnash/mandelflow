"""Read a Zarr → render a single frame as PNG.

Minimum viable viewer for verifying compute stages produce plausible
arrays. Bigger renderer concerns (per-stage colormaps, MP4 stitching,
animation) live in their own modules — this one is pure single-frame.

The compute stages store `iterations` in math orientation (y increases
with row index); `imshow(origin="lower")` is what re-flips it back to
the Mandelbrot we recognise (cardioid open to the right, period-2 bulb
on the left).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr


def render_frame_to_png(
    iterations: np.ndarray,
    output_path: str | Path,
    cmap: str = "twilight_shifted",
    dpi: int = 150,
) -> None:
    """Render a 2D iteration array to a PNG file.

    No axes, no colorbar — just the fractal. The renderer trusts the
    encoding contract: bounded-set pixels carry the array's maximum
    value (the `max_iter` sentinel from `compute_frame`), so the chosen
    colormap's top end lands on the set itself.
    """
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(iterations, cmap=cmap, origin="lower")
    ax.set_axis_off()
    fig.savefig(output_path, bbox_inches="tight", pad_inches=0, dpi=dpi)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render a Zarr frame to PNG")
    parser.add_argument("--input", type=Path, required=True,
                        help="Path to an iterations Zarr store.")
    parser.add_argument("--frame", type=int, default=0,
                        help="Frame index to render (default: 0).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output PNG path. Defaults to <input>.png.")
    parser.add_argument("--cmap", default="twilight_shifted",
                        help="matplotlib colormap name.")
    args = parser.parse_args(argv)

    if args.output is None:
        args.output = args.input.with_suffix(".png")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    ds = xr.open_zarr(args.input)
    iterations = ds.iterations.isel(frame=args.frame).values
    print(f"render: {args.input} [frame={args.frame}, shape={iterations.shape}]")
    print(f"  range: {int(iterations.min())} .. {int(iterations.max())}")

    render_frame_to_png(iterations, args.output, cmap=args.cmap)
    print(f"  wrote: {args.output}")


if __name__ == "__main__":
    main()
