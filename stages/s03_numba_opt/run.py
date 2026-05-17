"""Stage 03: numba @vectorize parallel + fastmath + early exits CLI."""

from __future__ import annotations

from pathlib import Path

from stages._cli import run_single_frame_stage
from stages.s03_numba_opt.compute import compute_frame


def main(argv: list[str] | None = None) -> None:
    run_single_frame_stage(
        stage_id="03",
        stage_label="numba_opt",
        compute_frame=compute_frame,
        default_output=Path("out/s03_numba_opt.zarr"),
        argv=argv,
    )


if __name__ == "__main__":
    main()
