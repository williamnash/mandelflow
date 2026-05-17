# mandelflow

A data engineering scaling study, using the Mandelbrot set as a vehicle. Each stage produces the same data product — a labelled Zarr store of iteration counts — at progressively larger scales, using progressively more powerful tools. From a 200×200 frame computed by a single Python `for` loop, up to a 1000-frame deep-zoom animation rendered across GPU pods on Kubernetes, written in parallel to a Zarr in Google Cloud Storage.

## The architecture

The whole project hangs on one design choice: **the data product is the Zarr store, not the rendered video**. Compute writes a labelled xarray-over-Zarr; rendering is a downstream, replayable step. This is what lets the same code run on a laptop and on a Kubernetes cluster — only the storage URL and the executor change.

```
┌──────────────────────┐   compute    ┌──────────────────────┐    read     ┌──────────────────────┐
│   Dagster            │  ────────▶   │   Zarr store         │  ◀────────  │   render/  (PNGs,    │
│   (asset model,      │              │   (local FS or       │             │   MP4, comparisons)  │
│    frame partitions, │              │    gs://bucket)      │             └──────────────────────┘
│    IOManagers)       │              │                      │    read     ┌──────────────────────┐
└──────────────────────┘              │   xarray dataset,    │  ◀────────  │   FastAPI viewer     │
                                      │   self-describing,   │             │   (stage 09 — read-  │
                                      │   one per run        │             │   only tile server)  │
                                      └──────────────────────┘             └──────────────────────┘

       Write path (Dagster) and read path (FastAPI / render) communicate only through the Zarr.
       Storage engine: raw Zarr for stages 00–06 (single writer); icechunk for stages 07+
       (transactional parallel writes, cloud-native, commits map onto Dagster materialisations).
```

## The data product

Every compute stage writes a Zarr conforming to this schema:

```
mandelflow_run.zarr/
├── iterations                # uint16, shape (N_frames, H, W), chunks (1, H, W)
└── coordinates
    ├── frame                 # int32, shape (N_frames,)
    ├── y                     # float32, shape (H,)  — pixel space
    ├── x                     # float32, shape (W,)
    ├── center_re             # float64, shape (N_frames,) — zoom schedule
    ├── center_im             # float64, shape (N_frames,)
    └── width                 # float64, shape (N_frames,)

attrs:
    stage_id, stage_name, max_iter, schedule_name,
    git_sha, wall_time_seconds, peak_memory_mb
```

Stages 00–06 write `N_frames = 1`. Stages 07+ unlock the frame dimension.

See [`docs/DESIGN.md`](docs/DESIGN.md) for why Zarr, why xarray, why Dagster, why FastAPI.

## The stages

| # | Stage | Tech | Storage | Target output scale | Reproducible from `pip install`? |
|---|---|---|---|---|---|
| 00 | `s00_naive` | Pure Python nested `for` loops | Raw Zarr (local FS) | 1 frame, 200×200 | ✓ |
| 01 | `s01_numpy` | NumPy vectorisation | Raw Zarr (local FS) | 1 frame, 1000×1000 | ✓ |
| 02 | `s02_numba` | `@numba.jit` | Raw Zarr (local FS) | 1 frame, 2000×2000 | ✓ |
| 03 | `s03_numba_opt` | `@vectorize` + fastmath + cardioid / periodicity early-exits | Raw Zarr (local FS) | 1 frame, 4000×4000 | ✓ |
| 04 | `s04_dask_local` | Dask `LocalCluster`, tiled across cores | Raw Zarr (local FS) | 1 frame, 10000×10000 | ✓ |
| 05 | `s05_gpu_torch` | PyTorch CUDA / MPS | Raw Zarr (local FS) | 1 frame, 16000×16000 | needs CUDA or MPS |
| 06 | `s06_gpu_shader` | GLSL via ModernGL (EGL on Linux, hidden window on macOS) | Raw Zarr (local FS) | 1 frame, 16000×16000 | needs OpenGL 4.1+ GPU |
| 07 | `s07_zoom_local` | Multi-frame zoom on one machine using s06's kernel with shared GL context | **icechunk** (local FS) | 100 frames, 1080p | needs OpenGL 4.1+ GPU |
| 08 | `s08_zoom_cloud` | Single GCE VM with a T4; s07's loop, output to GCS | Zarr in GCS | 200 frames, 1080p | needs GCP creds |
| 09 | `s09_zoom_fanout` | GKE multi-Pod fan-out, frame range per Pod | **icechunk** in GCS | 1000 frames, 1080p | needs GCP creds |
| 10 | `s10_viewer_fastapi` | FastAPI tile server over precomputed Zarrs (frame PNGs + slippy-map tiles) | reads either backend | – | ✓ (CPU-only) |

**Reproducibility contract:** every stage marked ✓ must run from `uv sync` followed by `uv run python -m stages.<stage_id>.run` on a stock laptop. Stages requiring GPU or GCP credentials must fail with a single clear line naming the missing prerequisite — never silently, never with a stack trace.

## Quickstart

```bash
uv sync                              # resolve & install from uv.lock
uv sync --extra gpu                  # add stages 05, 06
uv sync --extra cloud                # add stage-08 cloud deps

# Run a single stage end-to-end (writes a Zarr, then renders frames + MP4)
uv run python -m stages.s00_naive.run

# Run the whole pipeline via Dagster — asset graph UI at http://localhost:3000
uv run dagster dev -m orchestration.definitions

# Re-render an existing Zarr with a different colormap
uv run python -m render.animation runs/2026-05-16.zarr --palette twilight

# Stage 10: tile server over precomputed Zarrs (CPU-only)
uv run uvicorn stages.s10_viewer_fastapi.main:app
```

Developing on macOS? See [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md) for stage-by-stage Mac notes (which stages run native, MPS limits, the `kind` cluster for stage-08 plumbing, Docker Desktop's GPU passthrough caveat).

## Repository layout

```
mandelflow/
├── pyproject.toml           # uv-managed deps (with `gpu` and `cloud` extras)
├── Dockerfile               # One image for stages 06, 08, 09 deployments
├── common/                  # Schedule, Zarr schema, colormap — shared by every stage
├── stages/                  # One package per stage; each exposes compute_frame(...)
│   ├── s00_naive/
│   ├── s01_numpy/
│   ├── s02_numba/
│   ├── s03_numba_opt/
│   ├── s04_dask_local/
│   ├── s05_gpu_torch/
│   ├── s06_gpu_shader/
│   ├── s07_zoom_local/
│   ├── s08_zoom_cloud/      # Single GCE VM with a T4 + terraform/
│   ├── s09_zoom_fanout/     # GKE multi-Pod fan-out + terraform/, k8s/, dev/
│   └── s10_viewer_fastapi/  # FastAPI tile server (read-only)
├── orchestration/           # Dagster: assets, frame partitions, IOManagers, resources
├── render/                  # Zarr → PNG, MP4, side-by-side comparison plots
├── bench/                   # Aggregate timings across stages; talk-style charts
└── docs/                    # DESIGN.md (the why), WEEKEND_PLAN.md, GOTCHAS.md
```

## Roadmap

- [ ] **`common/`** — `schedule.py` (canonical zoom path), `store.py` (xarray + Zarr schema), `colormap.py`.
- [ ] **Stages 00–03** — single-frame CPU implementations, all writing to the same Zarr schema.
- [ ] **`render/`** — Zarr → PNG + MP4 via ffmpeg.
- [ ] **`orchestration/`** — Dagster asset graph, frame partitions, `LocalZarrIOManager`. `dagster dev` shows the pipeline.
- [ ] **Stage 04** — Dask local cluster, one big single-frame render, still raw Zarr.
- [ ] **Stage 07** — Frame dimension fanned across Dask workers; storage backed by icechunk for transactional parallel writes. First multi-frame animation rendered from a real Zarr.
- [ ] **Stages 05, 06** — GPU stages. Native on macOS via MPS (stage 05) and a hidden pygame GL context (stage 06); EGL standalone context for Linux containers. Stage 06 (headless EGL in a CUDA container) is the riskiest single step.
- [ ] **Stage 08** — Single GCE VM with a T4; Terraform provisions the VM, GCS bucket, attached service account; s07's loop runs in the container with output to `gs://bucket/run.zarr`.
- [ ] **Stage 09** — Terraform GKE Standard + GPU node pool + Workload Identity Federation; frame ranges fanned across Pods via Dagster K8s executor; icechunk repo in `gs://bucket/run.icechunk` via `IcechunkGCSIOManager`.
- [ ] **Stage 10** — FastAPI tile server over precomputed Zarrs (frame PNGs + slippy-map tiles). Pure CPU; deploys to Cloud Run and scales to zero.
- [ ] **CI** — `pr.yml` runs stages 00–04 + 07 at small scales; lints Terraform; validates Dagster definitions.
- [ ] **`bench/`** — aggregate run.json across stages, regenerate the talk-style scaling chart.

See [`docs/WEEKEND_PLAN.md`](docs/WEEKEND_PLAN.md) for the chronological build order and [`docs/GOTCHAS.md`](docs/GOTCHAS.md) for the known sharp edges.

## Inspiration

Mirrors the pedagogical arc of the *Scalable Computing with the Mandelbrot Set* talk and extends it with the platform layer: Dagster as orchestrator, Zarr as the canonical data product, FastAPI as the read service — running locally or on Kubernetes against the same code.
