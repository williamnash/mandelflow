"""Stage 12: read-only FastAPI viewer over precomputed Zarrs.

Dagster owns the write path; this service owns the read path; the Zarr is
the contract between them (DESIGN.md §4). Endpoints:

  GET /healthz                              — liveness probe
  GET /runs                                 — list stores under the root
  GET /runs/{run_id}                        — run + per-frame metadata
  GET /runs/{run_id}/frame/{i}.png          — colourised frame PNG
  GET /tiles/{run_id}/{frame}/{z}/{x}/{y}.png — slippy-map tile

Pure CPU: I/O + colormap + PNG encoding. No GPU, no GL context — so it
scales to zero on Cloud Run. On-demand rendering of uncomputed regions is
deliberately out of scope (DESIGN.md §11).

Tiles are sliced from the stored iterations array per request rather than
from a pregenerated pyramid: one frame is one Zarr chunk, so the read is a
single chunk fetch and the quadtree arithmetic is just array slicing. A
materialised pyramid (DESIGN.md §11) becomes worthwhile when frames outgrow
"slice + resize in a request" — it would slot in behind the same URL shape.

The store root comes from `MANDELFLOW_STORE_ROOT` (default `out/`), read
per request so one process can follow a remounted volume. Run IDs are
validated against the actual directory listing, which doubles as path-
traversal protection: only direct children of the root are addressable.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import xarray as xr
from fastapi import FastAPI, HTTPException, Response

from common.store import open_iterations_dataset
from render.palettes import DEFAULT_FREQ, DEFAULT_PALETTE, colorize, get_cmap

TILE_SIZE = 256
RUN_SUFFIXES = (".zarr", ".icechunk")

app = FastAPI(title="mandelflow viewer", docs_url="/docs")


def _store_root() -> Path:
    return Path(os.environ.get("MANDELFLOW_STORE_ROOT", "out"))


def _list_runs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.name.endswith(RUN_SUFFIXES))


@lru_cache(maxsize=8)
def _open_run(root: str, run_id: str) -> xr.Dataset:
    return open_iterations_dataset(Path(root) / run_id)


def _get_run(run_id: str) -> xr.Dataset:
    root = _store_root()
    if run_id not in _list_runs(root):
        raise HTTPException(404, detail=f"run {run_id!r} not found under {root}")
    return _open_run(str(root), run_id)


def _frame_iterations(ds: xr.Dataset, run_id: str, frame: int) -> np.ndarray:
    n_frames = ds.sizes["frame"]
    if not 0 <= frame < n_frames:
        raise HTTPException(404, detail=f"frame {frame} out of range for {run_id!r} (0..{n_frames - 1})")
    # flipud: stored arrays are math-orientation (y up); images are row-0-top.
    return np.flipud(ds.iterations.isel(frame=frame).values)


def _png_response(rgb: np.ndarray, resize_to: int | None = None) -> Response:
    from PIL import Image

    img = Image.fromarray(rgb)
    if resize_to is not None and img.size != (resize_to, resize_to):
        img = img.resize((resize_to, resize_to), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


def _colorize_or_400(iterations: np.ndarray, cmap: str, freq: float) -> np.ndarray:
    try:
        get_cmap(cmap)
    except KeyError:
        raise HTTPException(400, detail=f"unknown palette {cmap!r}; see render.palettes.available()")
    return colorize(iterations, cmap=cmap, freq=freq)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/runs")
def runs() -> dict:
    return {"runs": _list_runs(_store_root())}


@app.get("/runs/{run_id}")
def run_metadata(run_id: str) -> dict:
    ds = _get_run(run_id)
    return {
        "id": run_id,
        "n_frames": int(ds.sizes["frame"]),
        "resolution": int(ds.sizes["y"]),
        "frames": [
            {
                "frame": int(ds.frame.values[i]),
                "center_re": float(ds.center_re.values[i]),
                "center_im": float(ds.center_im.values[i]),
                "width": float(ds.width.values[i]),
            }
            for i in range(ds.sizes["frame"])
        ],
    }


@app.get("/runs/{run_id}/frame/{frame}.png")
def frame_png(
    run_id: str,
    frame: int,
    cmap: str = DEFAULT_PALETTE,
    freq: float = DEFAULT_FREQ,
) -> Response:
    iterations = _frame_iterations(_get_run(run_id), run_id, frame)
    return _png_response(_colorize_or_400(iterations, cmap, freq))


@app.get("/tiles/{run_id}/{frame}/{z}/{x}/{y}.png")
def tile_png(
    run_id: str,
    frame: int,
    z: int,
    x: int,
    y: int,
    cmap: str = DEFAULT_PALETTE,
    freq: float = DEFAULT_FREQ,
) -> Response:
    iterations = _frame_iterations(_get_run(run_id), run_id, frame)
    resolution = iterations.shape[0]
    n_tiles = 2**z
    if z < 0 or n_tiles > resolution:
        raise HTTPException(404, detail=f"zoom {z} out of range for resolution {resolution}")
    if not (0 <= x < n_tiles and 0 <= y < n_tiles):
        raise HTTPException(404, detail=f"tile ({x}, {y}) out of range at zoom {z}")
    r0, r1 = y * resolution // n_tiles, (y + 1) * resolution // n_tiles
    c0, c1 = x * resolution // n_tiles, (x + 1) * resolution // n_tiles
    # Colourise the whole frame, then slice: colorize() identifies the set
    # as the array max, which only holds frame-wide, not per-tile.
    rgb = _colorize_or_400(iterations, cmap, freq)
    return _png_response(rgb[r0:r1, c0:c1], resize_to=TILE_SIZE)
