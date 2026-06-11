"""Stage 12 viewer: read-only FastAPI service over precomputed Zarrs.

Exercises the contract from DESIGN.md §4: list runs, serve frame PNGs,
serve slippy-map tiles. Pure CPU — no GPU or GL required, so no skipif
guards. Stores are built with the canonical `common.store` schema.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from common.store import create_iterations_dataset, write_frame

RESOLUTION = 64
N_FRAMES = 2


@pytest.fixture()
def store_root(tmp_path):
    """A store root holding one canonical two-frame run."""
    path = tmp_path / "demo.zarr"
    create_iterations_dataset(path, n_frames=N_FRAMES, resolution=RESOLUTION)
    rng = np.random.default_rng(0)
    for i in range(N_FRAMES):
        iters = rng.integers(0, 64, size=(RESOLUTION, RESOLUTION), dtype=np.uint16)
        write_frame(path, i, iters, center_re=-0.75, center_im=0.0, width=3.5 / (i + 1))
    return tmp_path


@pytest.fixture()
def client(store_root, monkeypatch):
    monkeypatch.setenv("MANDELFLOW_STORE_ROOT", str(store_root))
    from stages.s12_viewer_fastapi.main import app

    return TestClient(app)


def _png_size(content: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(content)).size


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_runs_lists_stores(client):
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json()["runs"] == ["demo.zarr"]


def test_run_metadata(client):
    resp = client.get("/runs/demo.zarr")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "demo.zarr"
    assert body["n_frames"] == N_FRAMES
    assert body["resolution"] == RESOLUTION
    assert body["frames"][0]["center_re"] == pytest.approx(-0.75)
    assert body["frames"][1]["width"] == pytest.approx(3.5 / 2)


def test_frame_png(client):
    resp = client.get("/runs/demo.zarr/frame/0.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert _png_size(resp.content) == (RESOLUTION, RESOLUTION)


def test_frame_png_palette_param(client):
    resp = client.get("/runs/demo.zarr/frame/0.png?cmap=ember&freq=0.2")
    assert resp.status_code == 200
    default = client.get("/runs/demo.zarr/frame/0.png")
    assert resp.content != default.content


def test_frame_unknown_palette_is_400(client):
    resp = client.get("/runs/demo.zarr/frame/0.png?cmap=not-a-palette")
    assert resp.status_code == 400


def test_frame_out_of_range_is_404(client):
    resp = client.get(f"/runs/demo.zarr/frame/{N_FRAMES}.png")
    assert resp.status_code == 404


def test_unknown_run_is_404(client):
    resp = client.get("/runs/nope.zarr")
    assert resp.status_code == 404
    assert client.get("/runs/nope.zarr/frame/0.png").status_code == 404


def test_run_id_traversal_rejected(client, tmp_path):
    # A run_id must name a direct child of the store root; anything
    # path-like is rejected rather than resolved.
    resp = client.get("/runs/..%2F..%2Fetc/frame/0.png")
    assert resp.status_code in (400, 404)


def test_tile_z0_is_whole_frame(client):
    resp = client.get("/tiles/demo.zarr/0/0/0/0.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert _png_size(resp.content) == (256, 256)


def test_tile_z1_quadrants(client):
    for x in range(2):
        for y in range(2):
            resp = client.get(f"/tiles/demo.zarr/0/1/{x}/{y}.png")
            assert resp.status_code == 200
            assert _png_size(resp.content) == (256, 256)


def test_tile_out_of_range_is_404(client):
    assert client.get("/tiles/demo.zarr/0/1/2/0.png").status_code == 404
    assert client.get("/tiles/demo.zarr/0/9/0/0.png").status_code == 404


def test_rewritten_run_is_picked_up_without_restart(client, store_root):
    # The dataset cache is keyed by store mtime: deleting and re-writing a
    # run (the normal re-materialise cycle) must serve the new data, not a
    # stale cached handle.
    assert client.get("/runs/demo.zarr").json()["n_frames"] == N_FRAMES

    import shutil

    shutil.rmtree(store_root / "demo.zarr")
    path = store_root / "demo.zarr"
    create_iterations_dataset(path, n_frames=N_FRAMES + 3, resolution=RESOLUTION)
    write_frame(path, 0, np.zeros((RESOLUTION, RESOLUTION), dtype=np.uint16),
                center_re=0.0, center_im=0.0, width=1.0)

    assert client.get("/runs/demo.zarr").json()["n_frames"] == N_FRAMES + 3


def test_tile_set_detection_is_frame_wide(tmp_path, monkeypatch):
    # colorize() paints the array max black ("the set"). A tile whose pixels
    # all escaped must not have its *local* max painted black — set
    # detection has to happen frame-wide, before slicing.
    path = tmp_path / "halves.zarr"
    create_iterations_dataset(path, n_frames=1, resolution=RESOLUTION)
    iters = np.full((RESOLUTION, RESOLUTION), 100, dtype=np.uint16)
    iters[:, : RESOLUTION // 2] = 10  # left half: escaped, no set pixels
    write_frame(path, 0, iters, center_re=-0.75, center_im=0.0, width=3.5)

    monkeypatch.setenv("MANDELFLOW_STORE_ROOT", str(tmp_path))
    from stages.s12_viewer_fastapi.main import app

    with TestClient(app) as c:
        left = np.asarray(Image.open(io.BytesIO(c.get("/tiles/halves.zarr/0/1/0/0.png").content)))
        right = np.asarray(Image.open(io.BytesIO(c.get("/tiles/halves.zarr/0/1/1/0.png").content)))
    assert not np.all(left.reshape(-1, 3) == 0, axis=1).any()
    assert np.all(right.reshape(-1, 3) == 0, axis=1).all()
