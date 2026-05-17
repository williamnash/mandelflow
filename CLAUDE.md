# CLAUDE.md

Operating context for Claude Code when working in this repo. Keep this file lean — it's loaded into every conversation.

## What this is

`mandelflow` is a data engineering scaling study built around the Mandelbrot set. Ten progressively scaled stages (`stages/s00_naive/` through `stages/s09_viewer_fastapi/`) demonstrate optimisation patterns from naive Python to Kubernetes-fanned GPU rendering. The repo's purpose is portfolio + pedagogy, not production.

## Load-bearing invariants

These exist for explicit design reasons (see `docs/DESIGN.md`). Don't violate them without flagging:

1. **The data product is the Zarr store, not the rendered video.** Compute stages write a labelled xarray-over-Zarr. MP4 / PNG output is downstream rendering, owned by `render/`. Never propose writing MP4 directly from a compute stage.
2. **Every stage exposes `compute_frame(center_re, center_im, width, resolution, max_iter) -> np.ndarray`** plus a `run.py` CLI. That's the contract Dagster's asset binds to.
3. **Raw Zarr for stages 00–06; icechunk for stages 07–08.** Stages 00–06 are single-writer (no transactional semantics needed). The icechunk migration at stage 07 is itself a teaching moment — don't move it earlier "for consistency."
4. **Reproducibility contract:** stages 00–04 and 07 must run from `uv sync && uv run python -m stages.<id>.run` on a stock laptop. No GPU, no cloud creds. Stages requiring GPU (05, 06) or cloud (08) must fail with **one clear line** naming the missing prerequisite — never a stack trace.
5. **Cross-platform GL.** `render/gl_context.py` picks hidden pygame (macOS) or EGL standalone (Linux containers). Same shader on both. Don't hard-code one path.
6. **Cross-platform torch.** `render/torch_device.py` picks CUDA → MPS → raise. Stage 05 runs in **float32** throughout (separate real / imag arrays, not complex dtypes) so the same code path works on CUDA, MPS, and CPU without MPS's historical complex-dtype gaps. Float32 caps useful zoom at ~10⁶; deep zoom lives in stage 06's shader, not stage 05.
7. **Stage 09 is read-only.** Tile server + frame PNG endpoints over precomputed Zarrs. No GPU, no GL context. On-demand rendering of arbitrary new regions is deliberately out of scope (would need a long-lived GL context per process — see DESIGN.md §11).

## Tooling

- **Package manager: `uv`.** `pyproject.toml` + committed `uv.lock`. Don't propose pip, poetry, or conda. Extras: `gpu` (torch, moderngl, pygame), `cloud` (dagster-k8s, dagster-gcp). Dev tooling in `[dependency-groups]`.
- **Orchestrator: Dagster.** Assets in `orchestration/`. `uv run dagster dev -m orchestration.definitions` for the UI. Don't propose Metaflow, Airflow, or Prefect — Dagster was chosen specifically for the asset-model alignment with Zarr-as-artifact.
- **Storage: Zarr v3 + xarray + (from stage 07) icechunk.** Always wrap stores in xarray for labelled dimensions.
- **One Dockerfile at repo root.** Multi-stage uv builder → CUDA runtime + Mesa EGL. Used by stages 06, 08, 09 with different entrypoints. Don't sprawl into per-stage Dockerfiles without a strong reason.

## Repository map

```
common/                  # Schedule (canonical zoom path), Zarr schema helpers, colormap
stages/sNN_<name>/       # One package per stage. Same contract, different implementation.
  s08_zoom_cloud/
    terraform/           # GKE + Workload Identity Federation
    k8s/                 # Pod / service manifests
    dev/                 # kind cluster config for local plumbing tests
  s09_viewer_fastapi/    # FastAPI tile server (read-only over precomputed Zarrs)
orchestration/           # Dagster: assets, partitions, IOManagers, resources
render/                  # Zarr → PNG / MP4; gl_context.py and torch_device.py live here
bench/                   # Aggregate timings across stages; talk-style charts
docs/
  DESIGN.md              # Architecture rationale — read before proposing structural changes
  LOCAL_DEV.md           # Mac dev story
  GOTCHAS.md             # Sharp edges journal — append when a new one is found
  WEEKEND_PLAN.md        # Chronological build order
.github/workflows/       # pr.yml (lint, test, terraform validate, docker build), deploy.yml
Dockerfile               # Stages 06, 08, 09 deployment image
pyproject.toml           # uv-managed deps
```

## Conventions

- **Stage directory naming: `sNN_lowercase_name`.** The `s` prefix preserves visual ordering and keeps the module a valid Python identifier (you can't `import 00_naive`).
- **Imports from the repo root.** `from common.schedule import canonical_schedule`, `from stages.s00_naive.compute import compute_frame`.
- **No top-level secrets.** GCP service accounts live in Workload Identity bindings; CI uses OIDC, not JSON keys.
- **Don't commit Zarrs, MP4s, or PNGs** (covered by `.gitignore` and `.dockerignore`). Reference outputs for tests live in `bench/results/` as small JSONs.
- **Comments only for the non-obvious WHY.** Don't narrate what well-named code already says.

## Before proposing changes

- **Structural changes** (new top-level dir, change to the stage contract, new orchestrator) — flag against `DESIGN.md` first. Those decisions are load-bearing and documented.
- **New dependencies** — confirm whether they belong in `dependencies`, the `gpu` extra, the `cloud` extra, or the `dev` group.
- **Cloud-deployable artifacts** — confirm they fit the one-Dockerfile model.
- **"Just add a script to do X"** — check whether X belongs to an existing stage's contract first.

## Pointers

- `docs/DESIGN.md` — full architecture rationale.
- `docs/LOCAL_DEV.md` — per-stage Mac developer checklist.
- `docs/GOTCHAS.md` — known sharp edges; append when a new one is found.
- `docs/WEEKEND_PLAN.md` — chronological build order.
- `~/workspace/talks/tae-2025-11-21/` — the *Scalable Computing with the Mandelbrot Set* talk this repo extends.
