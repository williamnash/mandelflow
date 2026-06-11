# Stage 12 — FastAPI viewer (the read layer)

Every stage before this one *writes* the data product. Stage 12 closes the loop: a **read-only FastAPI service over precomputed Zarrs**. Dagster owns the write path, FastAPI owns the read path, and the Zarr is the contract between them — the modern data-engineering split, decoupled through a durable artifact (DESIGN.md §4).

Pure CPU: I/O + colormap + PNG encoding. No GPU, no GL context, no compute kernel — which is why this is the one stage without a `compute_frame`. It deploys from the same repo-root Docker image as the compute stages (one-image model) with a uvicorn entrypoint, and scales to zero on Cloud Run.

## Run it

```bash
# Produce something to look at, if out/ is empty:
uv run python -m stages.s07_zoom_local.run        # or any compute stage

# Serve it:
uv run uvicorn stages.s12_viewer_fastapi.main:app
# → http://127.0.0.1:8000/docs for the interactive API browser
```

The store root defaults to `out/`; point elsewhere with `MANDELFLOW_STORE_ROOT=/path/to/stores` or `MANDELFLOW_STORE_ROOT=gs://bucket/prefix` (raw `.zarr` and `.icechunk` runs both work — `common.store.open_iterations_dataset` handles either backend, and gs:// listing goes through gcsfs). For local roots a deleted-and-rewritten run is picked up without a restart (caches key on the store directory's mtime); gs:// runs and in-place icechunk commits serve the snapshot first opened until restart.

## Endpoints

| Route | Returns |
|---|---|
| `GET /healthz` | liveness |
| `GET /runs` | run IDs under the store root |
| `GET /runs/{run_id}` | n_frames, resolution, per-frame `(center, width)` coords |
| `GET /runs/{run_id}/frame/{i}.png` | colourised frame; `?cmap=` + `?freq=` as in `render.palettes` |
| `GET /tiles/{run_id}/{frame}/{z}/{x}/{y}.png` | 256×256 slippy-map tile of one frame |

Colouring is `render.palettes.colorize` — the same per-pixel, statistic-free cyclic √-count mapping the MP4 stitcher uses, so the viewer and the rendered video agree exactly.

## Tiles without a pyramid

DESIGN.md §11 sketches a materialised tile *pyramid* as its own artifact. v1 skips it: each frame is a single `(1, H, W)` Zarr chunk, and the *colourised* frame is LRU-cached — so a viewport's worth of tile requests pays one chunk read + one colorize, then pure slicing. The quadtree arithmetic lives in the URL (`2^z` tiles per side); a real pyramid store can slot in behind the same routes when frame resolution outgrows slice-and-resize.

One subtlety worth reading in `main.py`: `colorize` identifies "the set" as the array max, which only holds **frame-wide**. Tiles are therefore sliced from the colourised frame, never colourised per-tile — otherwise an all-escaped tile would paint its local max black.

## Deliberately out of scope

On-demand rendering of regions that were never computed. That would need the s06 shader and a long-lived GL context per process (`render/gl_context.py` is per-call today — DESIGN.md §11). If it ever lands, it's a separate GPU service against the same Zarr, not a feature of this one.
