"""Stage 00: naive Mandelbrot CLI.

This stage is deliberately slow — at 256x256 a full render takes
seconds; at 1024x1024 it takes minutes. That cost is the baseline
later stages improve on.
"""

from __future__ import annotations

from pathlib import Path

from stages._cli import run_single_frame_stage
from stages.s00_naive.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    run_single_frame_stage(
        stage_id="00",
        stage_label="naive",
        compute_frame=compute_frame,
        default_output=Path("out/s00_naive.zarr"),
        argv=argv,
    )


if __name__ == "__main__":
    main()
