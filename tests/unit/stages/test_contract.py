"""Every compute stage honours the `compute_frame` contract.

CLAUDE.md invariant #2: the first five parameters are
`(center_re, center_im, width, resolution, max_iter)`, in that order.
Stages may append keyword-only extras with defaults (s05's `device`,
s06's `ctx`) — what must never drift is the shared prefix Dagster's
asset binds to.

Discovery is dynamic: a new stage directory is covered the moment it
gains a `compute.py`, with no test edit. s12 is excluded by design —
it is the read layer and has no kernel.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

STAGES_DIR = Path(__file__).resolve().parents[3] / "stages"
NO_KERNEL = {"s12_viewer_fastapi"}

CONTRACT_PARAMS = ("center_re", "center_im", "width", "resolution", "max_iter")


def _stage_dirs() -> list[str]:
    return sorted(
        p.name for p in STAGES_DIR.iterdir()
        if p.is_dir() and p.name.startswith("s") and p.name not in NO_KERNEL
        and (p / "compute.py").exists()
    )


@pytest.mark.parametrize("stage", _stage_dirs())
def test_compute_frame_signature(stage):
    try:
        module = importlib.import_module(f"stages.{stage}.compute")
    except ImportError as e:
        pytest.skip(f"optional deps missing for {stage}: {e}")

    fn = getattr(module, "compute_frame", None)
    assert fn is not None, f"stages/{stage}/compute.py has no compute_frame"

    params = list(inspect.signature(fn).parameters.values())
    names = tuple(p.name for p in params[: len(CONTRACT_PARAMS)])
    assert names == CONTRACT_PARAMS, (
        f"{stage}.compute_frame breaks the contract prefix: {names}"
    )
    for extra in params[len(CONTRACT_PARAMS):]:
        assert extra.default is not inspect.Parameter.empty, (
            f"{stage}.compute_frame extra param {extra.name!r} must have a default"
        )
