"""s09 fan-out: per-frame coords must survive concurrent task commits.

Production finding (portfolio-stride-002): iterations landed for all 600
frames but center_re/center_im/width coords for only 150 — each coord
array is a single chunk, every task region-wrote it alongside its frames,
and the conflict-solver rebase kept only the last committer's copy.

The fix has two halves, both pinned here: the dispatcher pre-populates
coords from the canonical schedule at schema init (it knows the whole
zoom path — there is nothing per-task about the coords), and task writes
carry only the iterations variable so they can never touch the coord
chunks again.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from common.config import from_env
from stages.s09_zoom_fanout_cpu.run import _init_schema, _open_repo, run_task

N_FRAMES = 6
RESOLUTION = 8


@pytest.fixture()
def small_run_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MANDELFLOW_OUTPUT", str(tmp_path / "run.icechunk"))
    monkeypatch.setenv("MANDELFLOW_PRESET", "demo")
    monkeypatch.setenv("MANDELFLOW_N_FRAMES", str(N_FRAMES))
    monkeypatch.setenv("MANDELFLOW_RESOLUTION", str(RESOLUTION))
    monkeypatch.setenv("MANDELFLOW_MAX_ITER", "16")
    return str(tmp_path / "run.icechunk")


def _open(path: str) -> xr.Dataset:
    repo = _open_repo(path)
    return xr.open_zarr(repo.readonly_session("main").store)


def test_init_schema_prepopulates_coords(small_run_env):
    repo = _open_repo(small_run_env)
    _init_schema(repo, from_env())
    ds = _open(small_run_env)
    for name in ("center_re", "center_im", "width"):
        assert np.isfinite(ds[name].values).all(), f"{name} not pre-populated at init"
    assert ds.width.values[0] > ds.width.values[-1]  # it's a zoom


def test_task_commits_cannot_clobber_coords(small_run_env):
    repo = _open_repo(small_run_env)
    _init_schema(repo, from_env())
    # Two tasks of a 2-pod run. Sequential is enough: the production bug
    # was each task's commit carrying a full coord chunk that was NaN
    # outside its own frames — if task writes still include coords, the
    # second commit wipes the first's frames' metadata.
    run_task(0, 2)
    run_task(1, 2)
    ds = _open(small_run_env)
    for name in ("center_re", "center_im", "width"):
        assert np.isfinite(ds[name].values).all(), f"{name} clobbered by task commits"
    # And the actual frames landed: every frame has escaped pixels.
    iters = ds.iterations.values
    assert (iters.reshape(N_FRAMES, -1).max(axis=1) > 0).all()
