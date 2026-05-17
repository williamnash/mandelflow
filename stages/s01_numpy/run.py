"""Stage 01: vectorised-numpy Mandelbrot CLI."""

from __future__ import annotations

from pathlib import Path

from stages._cli import run_single_frame_stage
from stages.s01_numpy.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    run_single_frame_stage(
        stage_id="01",
        stage_label="numpy",
        compute_frame=compute_frame,
        default_output=Path("out/s01_numpy.zarr"),
        argv=argv,
    )


if __name__ == "__main__":
    main()
