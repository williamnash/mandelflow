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
single chunk fetch and the quadtree arithmetic is just array slicing. The
colourised frame is LRU-cached, so a viewport's worth of tile requests
pays one chunk read + one colorize, then pure slicing. A materialised
pyramid (DESIGN.md §11) becomes worthwhile when frames outgrow that — it
would slot in behind the same URL shape.

The store root comes from `MANDELFLOW_STORE_ROOT` (default `out/`) and may
be a local directory or a `gs://bucket/prefix`. Run IDs must be bare child
names ending in a known store suffix — path-shaped IDs are rejected before
any filesystem access. For local roots, caches are keyed by the store
directory's mtime, so a deleted-and-rewritten run is picked up without a
restart; an in-place icechunk commit (which may not touch the root dir's
mtime) and gs:// roots serve the snapshot first opened until restart.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import xarray as xr
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse

from common.store import STORE_SUFFIXES, open_iterations_dataset
from render.palettes import DEFAULT_FREQ, DEFAULT_PALETTE, available, colorize

TILE_SIZE = 256
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="mandelflow viewer", docs_url="/docs")


def _store_root() -> str:
    return os.environ.get("MANDELFLOW_STORE_ROOT", "out").rstrip("/")


def _list_runs(root: str) -> list[str]:
    if root.startswith("gs://"):
        import gcsfs

        fs = gcsfs.GCSFileSystem()
        try:
            entries = fs.ls(root[len("gs://"):])
        except FileNotFoundError:
            return []
        return sorted(e.rstrip("/").rsplit("/", 1)[-1] for e in entries
                      if e.rstrip("/").endswith(STORE_SUFFIXES))
    path = Path(root)
    if not path.is_dir():
        return []
    return sorted(p.name for p in path.iterdir() if p.name.endswith(STORE_SUFFIXES))


def _validate_run_id(run_id: str) -> None:
    """Traversal protection without a per-request directory listing: a run
    ID must be a bare child name in a known store format."""
    if ("/" in run_id or "\\" in run_id or run_id.startswith(".")
            or not run_id.endswith(STORE_SUFFIXES)):
        raise HTTPException(404, detail=f"run {run_id!r} is not a valid run id")


def _cache_token(root: str, run_id: str) -> int:
    """Local stores: the directory mtime, so a rewritten run busts the
    cache. gs:// stores: constant (snapshot pinned until restart)."""
    if root.startswith("gs://"):
        return 0
    try:
        return Path(root, run_id).stat().st_mtime_ns
    except FileNotFoundError:
        raise HTTPException(404, detail=f"run {run_id!r} not found under {root}")


@lru_cache(maxsize=8)
def _open_run(root: str, run_id: str, token: int) -> xr.Dataset:
    try:
        return open_iterations_dataset(f"{root}/{run_id}")
    except FileNotFoundError:
        raise HTTPException(404, detail=f"run {run_id!r} not found under {root}")


def _get_run(run_id: str) -> tuple[xr.Dataset, str, int]:
    root = _store_root()
    _validate_run_id(run_id)
    token = _cache_token(root, run_id)
    return _open_run(root, run_id, token), root, token


@lru_cache(maxsize=8)
def _rgb_frame(root: str, run_id: str, token: int, frame: int,
               cmap: str, freq: float) -> np.ndarray:
    """Colourised (H, W, 3) frame. One entry serves the frame PNG and every
    tile of that frame; ~14 MB per 2160² entry at maxsize=8.

    Colourising happens frame-wide, never per-tile: colorize() identifies
    the set as the array max, which only holds for the whole frame.
    """
    ds = _open_run(root, run_id, token)
    # flipud: stored arrays are math-orientation (y up); images are row-0-top.
    iterations = np.flipud(ds.iterations.isel(frame=frame).values)
    return colorize(iterations, cmap=cmap, freq=freq)


def _rgb_or_error(run_id: str, frame: int, cmap: str, freq: float) -> np.ndarray:
    ds, root, token = _get_run(run_id)
    n_frames = ds.sizes["frame"]
    if not 0 <= frame < n_frames:
        raise HTTPException(404, detail=f"frame {frame} out of range for {run_id!r} (0..{n_frames - 1})")
    try:
        return _rgb_frame(root, run_id, token, frame, cmap, freq)
    except KeyError:
        raise HTTPException(400, detail=f"unknown palette {cmap!r}; see render.palettes.available()")


def _png_response(rgb: np.ndarray, resize_to: int | None = None) -> Response:
    from PIL import Image

    img = Image.fromarray(rgb)
    if resize_to is not None and img.size != (resize_to, resize_to):
        img = img.resize((resize_to, resize_to), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """The interactive UI: run picker, frame scrubber + play, palette
    switcher, and a Leaflet pan/zoom map over the tile endpoints."""
    return (STATIC_DIR / "index.html").read_text()


@app.get("/palettes")
def palettes() -> dict:
    return {"palettes": available(), "default": DEFAULT_PALETTE}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/runs")
def runs() -> dict:
    return {"runs": _list_runs(_store_root())}


@app.get("/runs/{run_id}")
def run_metadata(run_id: str) -> dict:
    ds, _, _ = _get_run(run_id)
    frame_idx = ds.frame.values
    center_re = ds.center_re.values
    center_im = ds.center_im.values
    width = ds.width.values
    return {
        "id": run_id,
        "n_frames": int(ds.sizes["frame"]),
        "resolution": int(ds.sizes["y"]),
        "frames": [
            {
                "frame": int(f),
                "center_re": float(cr),
                "center_im": float(ci),
                "width": float(w),
            }
            for f, cr, ci, w in zip(frame_idx, center_re, center_im, width)
        ],
    }


@app.get("/runs/{run_id}/frame/{frame}.png")
def frame_png(
    run_id: str,
    frame: int,
    cmap: str = DEFAULT_PALETTE,
    freq: float = DEFAULT_FREQ,
) -> Response:
    return _png_response(_rgb_or_error(run_id, frame, cmap, freq))


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
    rgb = _rgb_or_error(run_id, frame, cmap, freq)
    resolution = rgb.shape[0]
    n_tiles = 2**z
    if z < 0 or n_tiles > resolution:
        raise HTTPException(404, detail=f"zoom {z} out of range for resolution {resolution}")
    if not (0 <= x < n_tiles and 0 <= y < n_tiles):
        raise HTTPException(404, detail=f"tile ({x}, {y}) out of range at zoom {z}")
    r0, r1 = y * resolution // n_tiles, (y + 1) * resolution // n_tiles
    c0, c1 = x * resolution // n_tiles, (x + 1) * resolution // n_tiles
    return _png_response(rgb[r0:r1, c0:c1], resize_to=TILE_SIZE)
