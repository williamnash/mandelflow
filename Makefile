# Convenience targets — everything here is just the documented uv commands.
# See README.md Quickstart and docs/LOCAL_DEV.md for the full story.

.PHONY: install install-gpu lint test bench dagster viewer docker smoke

install:           ## Base deps from uv.lock (stages 00-04, 07, tests)
	uv sync

install-gpu:       ## + torch / moderngl / pygame (stages 05, 06)
	uv sync --extra gpu

lint:              ## Same check CI runs
	uv run ruff check .

test:              ## Full suite; GPU/GL tests self-skip without hardware
	uv run pytest tests/ -v

bench:             ## Re-measure kernel throughput on this machine -> bench/results/
	uv run python -m bench.kernel_throughput

dagster:           ## Asset-graph UI at http://localhost:3000
	uv run dagster dev -m orchestration.definitions

viewer:            ## Stage-12 tile server at http://localhost:8000 (docs at /docs)
	uv run uvicorn stages.s12_viewer_fastapi.main:app --reload

docker:            ## The one deployment image (stages 06, 08-12)
	docker build -t mandelflow:dev .

smoke:             ## 30-second end-to-end: compute s00 -> render PNG
	uv run python -m stages.s00_naive.run
	uv run python -m render.frame --input out/s00_naive.zarr
	@echo "wrote out/s00_naive.png"

help:              ## This list
	@grep -E '^[a-z-]+: ' $(MAKEFILE_LIST) | sed 's/:.*##/ —/'
