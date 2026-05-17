"""Multi-frame Zarr → MP4 stitcher.

Pixel-perfect: PNG frame dimensions match the iteration array exactly.
Each frame's iterations array is colormapped via matplotlib's palette,
converted to 8-bit RGB, and saved through PIL — no matplotlib axis /
canvas system in the loop, so there's no margin-trimming and no
up/downsampling.

Frames are normalised to a fixed `[0, max_value]` range (the global max
across all frames) so colours stay consistent throughout the zoom.
Per-frame normalisation would flicker as the iteration range shifts.

For a 4K square (2160×2160) demo zoom: compute at `--resolution 2160`,
then run this stitcher. The MP4 output ends up at 2160×2160.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import matplotlib
import numpy as np
import xarray as xr
from PIL import Image


def render_zarr_to_mp4(
    zarr_path: str | Path,
    output_path: str | Path,
    fps: int = 30,
    cmap: str = "twilight_shifted",
    crf: int = 18,
) -> None:
    """Stitch every frame of a multi-frame Zarr into an MP4.

    Output dimensions match the iteration array dimensions exactly
    (one MP4 pixel per iteration array entry). For libx264 / yuv420p
    compatibility, both H and W must be even; if either is odd we pad
    by one row/column at write time.

    `crf` controls quality: 17 ≈ visually lossless, 23 = ffmpeg
    default, 28 = noticeable artifacts. Lower = bigger file.
    """
    ds = xr.open_zarr(zarr_path)
    n_frames = ds.sizes["frame"]
    if n_frames < 1:
        raise ValueError(f"Zarr {zarr_path} has no frames.")

    global_max = max(int(ds.iterations.max().compute()), 1)
    palette = matplotlib.colormaps[cmap]

    with tempfile.TemporaryDirectory() as tmpdir:
        for k in range(n_frames):
            iters = ds.iterations.isel(frame=k).values
            # Normalize to [0,1], apply colormap → (H, W, 4) float, take RGB.
            normalized = iters.astype(np.float32) / global_max
            rgb = (palette(normalized)[..., :3] * 255).astype(np.uint8)
            # The shader stores y increasing with row index (math orientation);
            # PIL / video stores rows top-down (image orientation). Flip once.
            rgb = np.flipud(rgb)
            # Ensure even dimensions (libx264 + yuv420p requirement).
            h, w = rgb.shape[:2]
            if h % 2 or w % 2:
                rgb = np.pad(
                    rgb,
                    ((0, h % 2), (0, w % 2), (0, 0)),
                    mode="edge",
                )
            Image.fromarray(rgb).save(Path(tmpdir) / f"frame_{k:05d}.png")

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", str(Path(tmpdir) / "frame_%05d.png"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", str(crf),
                "-movflags", "+faststart",   # web-friendly: moov atom up front
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render a multi-frame Zarr to MP4")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fps", type=int, default=30,
                        help="Frame rate. Lower = slower playback. 24 = cinematic, 30 = standard, 60 = smooth.")
    parser.add_argument("--cmap", default="twilight_shifted",
                        help="matplotlib colormap. Try 'magma', 'inferno', 'viridis', 'twilight'.")
    parser.add_argument("--crf", type=int, default=18,
                        help="x264 quality. 17 = visually lossless, 23 = default, 28 = artifacts.")
    args = parser.parse_args(argv)

    if args.output is None:
        args.output = args.input.with_suffix(".mp4")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(f"animation: {args.input}")
    render_zarr_to_mp4(
        args.input, args.output,
        fps=args.fps, cmap=args.cmap, crf=args.crf,
    )
    print(f"  wrote: {args.output}")


if __name__ == "__main__":
    main()
