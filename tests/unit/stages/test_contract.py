"""Every compute stage honours the `compute_frame` contract.

CLAUDE.md invariant #2: the first five parameters are
`(center_re, center_im, width, resolution, max_iter)`, in that order.
Stages may append keyword-only extras with defaults (s05's `device`,
s06's `ctx`) — what must never drift is the shared prefix Dagster's
asset binds to.

Discovery is dynamic and exhaustive: every stage directory must either
have a `compute.py` or appear in NO_KERNEL with a reason — a new stage
shipping without a kernel fails loudly instead of silently escaping
coverage. Variant kernels (any `compute_frame*` callable, e.g. s05's
`compute_frame_compiled`) are held to the same prefix.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

STAGES_DIR = Path(__file__).resolve().parents[3] / "stages"
NO_KERNEL = {
    "s10_zoom_cloud_gpu": "placeholder — GCP GPU quota blocked",
    "s12_viewer_fastapi": "read layer — serves precomputed data, no kernel",
}

CONTRACT_PARAMS = ("center_re", "center_im", "width", "resolution", "max_iter")


def _stage_dirs() -> list[str]:
    return sorted(
        p.name for p in STAGES_DIR.iterdir()
        if p.is_dir() and p.name[0] == "s" and p.name[1].isdigit()
        and p.name not in NO_KERNEL
    )


@pytest.mark.parametrize("stage", _stage_dirs())
def test_compute_frame_signature(stage):
    assert (STAGES_DIR / stage / "compute.py").exists(), (
        f"stages/{stage}/ has no compute.py — add one or list the stage "
        "in NO_KERNEL with a reason"
    )
    try:
        module = importlib.import_module(f"stages.{stage}.compute")
    except ImportError as e:
        pytest.skip(f"optional deps missing for {stage}: {e}")

    kernels = {
        name: fn for name, fn in vars(module).items()
        if name.startswith("compute_frame") and callable(fn)
    }
    assert "compute_frame" in kernels, f"stages/{stage}/compute.py has no compute_frame"

    for name, fn in kernels.items():
        params = list(inspect.signature(fn).parameters.values())
        prefix = tuple(p.name for p in params[: len(CONTRACT_PARAMS)])
        assert prefix == CONTRACT_PARAMS, (
            f"{stage}.{name} breaks the contract prefix: {prefix}"
        )
        for extra in params[len(CONTRACT_PARAMS):]:
            assert extra.default is not inspect.Parameter.empty, (
                f"{stage}.{name} extra param {extra.name!r} must have a default"
            )
