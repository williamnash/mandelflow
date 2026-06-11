# Contributing

This is a portfolio / pedagogy project, but PRs that sharpen a stage's lesson, fix a sharp edge, or extend the scaling story are welcome.

## Setup

```bash
uv sync                 # base deps (stages 00-04, 07, tests)
uv sync --extra gpu     # stages 05-06 (torch >= 2.7, moderngl, pygame)
pre-commit install      # ruff on commit, mirrors CI
make help               # the common commands
```

## Ground rules

1. **Red/green TDD for behaviour changes.** Write the failing test in `tests/` first, watch it fail for the right reason, then implement. GPU/GL tests carry `skipif` guards so they skip — never fail — without hardware. Docs and infra (terraform, k8s, workflows) are exempt.
2. **One optimization per stage.** Each `stages/sNN_*` teaches exactly one thing (see its README). Don't backport a later stage's trick into an earlier stage — that erases the lesson. New tricks go in a new variant (like s05's `compute_frame_compiled`) or a new stage.
3. **The stage contract is pinned.** `compute_frame(center_re, center_im, width, resolution, max_iter)` — extras must be keyword-with-default. `tests/unit/stages/test_contract.py` enforces this for every `compute_frame*`.
4. **The data product is the Zarr, not the video.** Compute stages write xarray-over-Zarr; rendering lives in `render/`. Never write MP4/PNG from a compute stage.
5. **Read `docs/DESIGN.md` before structural changes** (new top-level dir, contract change, orchestrator swap) and `docs/GOTCHAS.md` before fighting a weird error — it's probably documented. Found a new sharp edge? Append it.
6. **Cloud stages fail with one clear line** naming the missing prerequisite (no GPU, no ADC) — never a stack trace. `common/gcp.py` has the credentials preflight.
7. **Don't commit Zarrs, MP4s, or PNGs** (gitignored). Benchmark evidence goes in `bench/results/` as JSON + SVG — keep the JSONs in git, they're how we caught a baseline regression once (GOTCHAS.md #22).

## Before opening a PR

```bash
make lint test          # what .github/workflows/pr.yml runs
```

CI also validates Dagster definitions and both terraform stacks; `terraform fmt` your `.tf` changes.
