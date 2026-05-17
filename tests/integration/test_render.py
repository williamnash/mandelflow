"""End-to-end: produce a Zarr via s00, render it to a PNG, verify the PNG."""

from __future__ import annotations

from PIL import Image

from render.frame import main as render_main
from stages.s00_naive.run import main as s00_main


def test_zarr_to_png_roundtrip(tmp_path):
    zarr_path = tmp_path / "s00.zarr"
    png_path = tmp_path / "s00.png"

    s00_main([
        "--center-re", "-0.75",
        "--center-im", "0.0",
        "--width", "3.5",
        "--resolution", "32",
        "--max-iter", "32",
        "--output", str(zarr_path),
    ])

    render_main([
        "--input", str(zarr_path),
        "--frame", "0",
        "--output", str(png_path),
    ])

    assert png_path.exists() and png_path.stat().st_size > 0
    with Image.open(png_path) as img:
        assert img.format == "PNG"
        assert img.size[0] > 0 and img.size[1] > 0
