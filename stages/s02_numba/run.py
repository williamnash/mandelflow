"""Stage 02: numba-JIT Mandelbrot CLI."""

from __future__ import annotations

from pathlib import Path

from stages._cli import run_single_frame_stage
from stages.s02_numba.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    run_single_frame_stage(
        stage_id="02",
        stage_label="numba",
        compute_frame=compute_frame,
        default_output=Path("out/s02_numba.zarr"),
        argv=argv,
    )


if __name__ == "__main__":
    main()
