"""Multi-frame Zarr → MP4 stitcher.

Reads each frame's iteration array from the Zarr, applies the shared
colormap, and pipes the PNGs into ffmpeg. The ffmpeg invocation uses
`yuv420p` + `libx264` for broad player compatibility.

Frames are normalised to a fixed `[0, max_value]` range — taken from
the global max across all frames — so colours stay consistent
throughout the zoom. Per-frame normalisation would flicker as the
iteration range shifts (a wide view contains both fast-escape pixels
and the set; a deep view may not).
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import xarray as xr


def render_zarr_to_mp4(
    zarr_path: str | Path,
    output_path: str | Path,
    fps: int = 30,
    cmap: str = "twilight_shifted",
    dpi: int = 100,
) -> None:
    """Stitch every frame of a multi-frame Zarr into an MP4."""
    ds = xr.open_zarr(zarr_path)
    n_frames = ds.sizes["frame"]
    if n_frames < 1:
        raise ValueError(f"Zarr {zarr_path} has no frames.")

    global_max = int(ds.iterations.max().compute())

    with tempfile.TemporaryDirectory() as tmpdir:
        for k in range(n_frames):
            iters = ds.iterations.isel(frame=k).values
            png_path = Path(tmpdir) / f"frame_{k:05d}.png"
            fig, ax = plt.subplots(figsize=(8, 8))
            ax.imshow(iters, cmap=cmap, origin="lower", vmin=0, vmax=global_max)
            ax.set_axis_off()
            fig.savefig(png_path, bbox_inches="tight", pad_inches=0, dpi=dpi)
            plt.close(fig)

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", str(Path(tmpdir) / "frame_%05d.png"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "23",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render a multi-frame Zarr to MP4")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--cmap", default="twilight_shifted")
    args = parser.parse_args(argv)

    if args.output is None:
        args.output = args.input.with_suffix(".mp4")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(f"animation: {args.input}")
    render_zarr_to_mp4(args.input, args.output, fps=args.fps, cmap=args.cmap)
    print(f"  wrote: {args.output}")


if __name__ == "__main__":
    main()
