# Design

Architecture rationale for `mandelflow`. Update this when a load-bearing decision changes.

## 1. The Zarr store is the data product

The canonical artifact every compute stage produces is a labelled xarray-over-Zarr — not a rendered video, not a PNG. Rendering is a downstream, replayable step.

Rationale:

- **Parallel-writable.** Each worker writes its own chunks to the same store. Video encoding is serial and cannot serve as the parallelisation unit.
- **Storage-agnostic.** Local filesystem for stages 00–07; `gs://bucket/run.zarr` for stage 08. The API is identical; only the URL changes.
- **Replayable.** Re-render with a different colormap, slice out a single frame, run downstream analysis, or feed it to the FastAPI viewer — all without recomputing.
- **Honest.** The iteration array is what the Mandelbrot computation actually produces. The video is a view.

The MP4 exists as a downstream artifact for shareability. It is not the contract.

## 2. xarray on top of Zarr

The dataset wrapping adds labelled dimensions:

- `ds.sel(frame=42)` and `ds.sel(width=1e-9)` work without manual index math.
- The store is self-describing — dimensions, coordinates, units travel with the data.
- It anchors the repo in the canonical scientific computing stack (climate, oceanography, Earth observation).

Overhead is one `Dataset` object per store; the labelled-dimension and self-describing wins justify it.

## 3. Dagster orchestrates

Dagster's asset model maps directly onto Zarr-as-data-product:

- **Assets ≡ Zarrs.** The asset graph is the Zarr lineage graph.
- **Partitions ≡ frames.** The `iterations` asset is always partitioned by frame. Single-frame stages (00–06) have one partition (frame=0); multi-frame stages (07+) have many. Intra-frame parallelism (Dask tiles in stage 04, GPU kernels in 05–06) happens inside the stage's `compute_frame`; inter-frame parallelism is Dagster's partition fan-out. Local execution uses a process pool over partitions; cluster execution uses one K8s job per partition.
- **IOManagers ≡ storage.** Configure-time choice between `LocalZarrIOManager` and `GCSIcechunkIOManager`. The compute code does not know where its bytes land.
- **Asset graph UI.** `dagster dev` shows lineage, materialisation status, and per-partition runs.

## 4. FastAPI is the read layer

Dagster owns the write path; FastAPI owns the read path; the Zarr is the contract between them. Stage 09's service is **read-only over precomputed Zarrs** and exposes:

- `GET /runs` — list materialised Zarrs in the configured store root.
- `GET /runs/{id}/frame/{i}.png` — read frame `i` from a Zarr, apply colormap, return PNG. Pure I/O + encoding.
- `GET /tiles/{run_id}/{z}/{x}/{y}.png` — serve precomputed slippy-map tiles from a tile pyramid stored alongside the iteration data. Backs a browser pan/zoom UI over what has already been computed.

The read service is pure CPU — no GPU, no GL context, scales to zero on Cloud Run. On-demand rendering of arbitrary uncached regions (which *would* need GPU + the stage-06 shader) is deliberately out of scope for v1; if needed it lands as a separate GPU service against the same Zarr.

The split decouples write and read paths through a durable artifact — the modern data-engineering shape.

## 5. Reproducibility contract

Stages 00–04 and 07 run from `uv sync` followed by `uv run python -m stages.<id>.run` on a stock laptop — no GPU, no cloud credentials.

Stages requiring GPU (05, 06) or cloud credentials (08) fail with **one clear line** naming the missing prerequisite (e.g. `Stage 05 requires a GPU (CUDA or MPS). Neither is available.`). Never silently; never with a stack trace.

CI runs stages 00–04 and 07 at small scales on every PR, verifying each produced Zarr matches a reference array within floating-point tolerance. GPU and cloud stages are import-tested and lint-tested only.

## 6. Stages decoupled from orchestration

Each stage exposes `compute_frame(center_re, center_im, width, resolution, max_iter) -> np.ndarray` and a `run.py` CLI. Dagster's asset calls into the stage to compute one partition. Consequences:

- Each stage is independently runnable without Dagster (`uv run python -m stages.s00_naive.run`).
- The orchestration layer lives in one place, not duplicated per stage.
- Adding a stage means one `compute_frame` implementation plus one Dagster job binding.

## 7. Storage engine: raw Zarr through stage 06, icechunk from stage 07

Stages 00–06 are single-writer and use raw Zarr — no transactional semantics needed. Stage 07 introduces parallel frame writers (Dask local cluster); stage 08 distributes them across K8s pods writing to GCS. At that point raw Zarr's chunk-level write semantics — "trust no two workers touch the same chunk" — are unsafe.

[Icechunk](https://earthmover.io/icechunk) is a transactional storage engine on top of Zarr v3, from Earthmover (the xarray/Zarr core maintainers). It adds the layer Zarr is missing for distributed cloud writes:

- **Coordinated parallel writes via sessions.** Each partition opens a writable session; the orchestrator commits atomically when all partitions complete. No racing on object-storage PUTs.
- **Git-like commits map onto Dagster materialisations.** Each Dagster run = one icechunk commit. Asset graph (orchestration lineage) + commit history (data lineage) line up end-to-end.
- **Cloud-object-storage native.** GCS / S3 is icechunk's primary backend — exactly the deployment target for stage 08. Avoids the "many small files in a bucket" problem raw Zarr exhibits on object stores.
- **Transparent reads.** `xr.open_zarr(session.store)` works without special handling. The FastAPI viewer gains time-travel queries (e.g. `/runs/{id}@{commit}/frame/{i}.png`) when it opts in.

`common/store.py` exposes two backend implementations behind the same dataset constructor: `RawZarrStore` for stages 00–06 and `IcechunkStore` for stages 07–08. Reads use the same `xr.open_zarr(...)` path for either.

**Maturity caveat:** icechunk reached 1.0 in late 2024; the ecosystem (blog posts, Stack Overflow) is still thin. Expect occasional "read the source" moments.

## 8. Cross-platform local development

The repo is developed on macOS (Apple Silicon) and deployed in Linux containers on GKE GPU pods. Two abstractions in `render/` absorb the split:

- **`gl_context.py`** — `make_offscreen_context()` picks the right offscreen GL backend per platform. macOS uses a hidden pygame window (Apple's OpenGL 4.1 implementation is exactly what the shader targets). Linux containers use `moderngl.create_standalone_context()` with EGL via Mesa.
- **`torch_device.py`** — `get_torch_device()` picks CUDA → MPS → fail. Stage 05 runs natively on Apple Silicon via MPS, with the float32 limitation (MPS does not support `complex128`).

Stage 08's local development is a layered loop:

1. **Multi-process Dagster executor on the laptop** — most asset code is developed here; identical to production except for the executor.
2. **Local `kind` cluster** (`stages/s08_zoom_cloud/dev/kind-cluster.yaml`) — for K8s plumbing tests: RBAC, pod specs, IOManager wiring. CPU compute (kind has no GPU on Apple Silicon).
3. **Real GKE with T4 pool** — final integration and actual GPU rendering. Used sparingly.

The Dagster asset definitions are identical across all three; only the executor config and IOManager change.

**Docker Desktop on macOS does not pass through the Apple GPU.** A container built for GKE's CUDA pool runs on a Mac via Mesa llvmpipe — software rendering, very slow. Use the container locally for "does it compile and start" checks only.

See [`LOCAL_DEV.md`](LOCAL_DEV.md) for the per-stage Mac developer checklist.

## 9. uv for package management

`uv` (from Astral) is the project's package manager and venv tool, replacing pip + venv + pip-tools.

- `pyproject.toml` holds dependencies; `uv.lock` (committed) gives a deterministic resolution.
- `uv sync` installs from the lockfile.
- Optional dependency groups split stage-specific deps: `uv sync --extra gpu` adds `torch`, `moderngl`, `pygame`; `uv sync --extra cloud` adds `dagster-k8s`, `dagster-gcp`.
- Dev tooling lives in a `[dependency-groups]` entry installed by default.
- CI runs `uv sync --frozen` for reproducibility.
- The Dockerfile uses uv in its builder stage to resolve deps into a project-local `.venv`, which the runtime stage copies forward.

## 10. Containers

Stages 06, 08, and 09 deploy as containers. A single Dockerfile at the repo root produces an image used by all three:

- **Stage 06's headless renderer** in Linux deployments — EGL via Mesa.
- **Stage 08's compute pods** on GKE — CUDA 12 runtime + EGL + the full stack.
- **Stage 09's viewer** on Cloud Run — same image, different entrypoint. CPU-only read service; the CUDA / EGL layers in the image go unused for stage 09, but one Dockerfile is simpler than two and the image is pulled once per Cloud Run revision.

One image keeps the build and deploy surface small. Different entrypoints select compute-worker vs viewer-server behaviour.

The image bundles CUDA 12 runtime, Mesa EGL (`libegl1`, `mesa-utils`), Python 3.11, the uv-resolved project venv, ffmpeg, and the project source.

Local development does not require Docker — macOS development is native (see [`LOCAL_DEV.md`](LOCAL_DEV.md)). The container is for deployment and the `kind` plumbing tests.

## 11. Known gaps

Things the architecture *names* but does not yet provide. Called out here so the docs don't oversell.

- **`GCSIcechunkIOManager`.** Referenced throughout but not yet a published package. Needs writing — a thin shim translating Dagster's `IOManager.load_input` / `handle_output` to icechunk session open / commit. Roughly a few hundred lines. Falls back to raw Zarr with `to_zarr(region=...)` if the icechunk integration proves heavier than expected; document the regression if that happens.
- **GL context lifecycle for any future on-demand rendering.** `render/gl_context.py` creates a fresh context per call. Any long-running process that uses it (e.g. a future render-on-demand service replacing stage 09's tile-only scope) needs a process-lifecycle singleton, not per-request initialisation. Stage 09's tile server avoids this entirely by serving only precomputed tiles.
- **The tile pyramid generator.** Stage 09 serves `/tiles/{z}/{x}/{y}.png` from a pyramid; the *generator* for that pyramid is its own piece of work — either an output of the compute stage or a downstream Dagster asset that reads the iterations Zarr and writes a pyramid Zarr/icechunk store.

## 12. Choosing a compute target

The ten stages exist because no single architecture wins every problem in this space. The decision between CPU and GPU — and between in-process and distributed CPU — turns on a small set of structural questions about the work, not on benchmark numbers. The same set of questions applies to picking a compute target for any embarrassingly-parallel numerical workload, not just Mandelbrot.

Heuristics in roughly decreasing order of decisiveness:

- **Per-element work vs dispatch overhead.** GPU stages dispatch one tensor op per arithmetic step. On Apple integrated MPS that's ~200–400 µs/op; on CUDA datacenter GPUs ~5–10 µs. CPU JIT (numba) has effectively zero per-step overhead — the loop runs as native machine code. Mandelbrot's inner loop does very little math per step (a few multiplies), so dispatch dominates on integrated GPUs and CPU JIT wins. Algorithms with denser per-step kernels (matrix multiply, FFT, convolution, neural-net layers) flip this — the per-op cost amortises and GPU wins from the first dispatch.

- **Per-element early termination.** Mandelbrot's per-pixel `break` on escape is free on CPU JIT. On GPU, SIMT lockstep means every pixel runs all `max_iter` iterations regardless of when each individually escapes. In practice s03 (CPU JIT) iterates an average of ~30× per pixel at the canonical view; s05 (GPU tensor ops) iterates 512×. Algorithms without divergent control flow (linear algebra, dense forward passes) suit GPU much better.

- **Working set vs device memory.** GPU memory is smaller than host RAM (typically 16–80 GB on cloud GPUs vs hundreds on a CPU node). When the dataset doesn't fit, you're streaming chunks across PCIe — usually CPU wins. Mandelbrot's working set is trivially small at any reasonable resolution; this isn't a constraint here, but it's the most common reason real workloads stay on CPU.

- **Setup amortisation.** GPU work has high fixed setup (kernel compile, device init, possible memory transfer). Single short queries don't amortise this; long-running batch jobs do. Stage 06's shader collapses the iteration loop into a single dispatched kernel so the per-frame setup is paid once and reused for many iterations — that's the move that beats per-op dispatch overhead.

- **Cross-machine scaling pressure.** When single-machine compute is the bottleneck, scaling out across GPU nodes is operationally heavy (every node needs CUDA drivers, model-state sync, larger images, scarcer hardware). Scaling out across CPU nodes via Dask is operationally simple — that's what s07 and s08 do. The Mandelbrot zoom is intentionally CPU-distributed: per-frame work fits comfortably on a single core's JIT, and frame-level fan-out scales linearly with node count.

### How the repo's stages embody these heuristics

| Stage | Wins when… | Loses when… |
|---|---|---|
| s03 numba_opt | Small-medium frames, single machine, divergent per-pixel control flow | Beyond single-machine throughput |
| s04 dask_local | Many CPU cores, intra-frame parallelism, single-machine | Single-frame work too small to amortise Dask overhead |
| s05 gpu_torch | Dense per-element math, no per-element branching, CUDA available | Per-op dispatch dominates (integrated GPU + tight loop) |
| s06 gpu_shader | Deep zoom needing long iteration in one kernel, GPU available | Infrastructure cost (EGL setup, container, GPU node) not justified by single-frame need |
| s07 / s08 zoom_dask | Many frames, embarrassingly parallel | Per-frame work so cheap that scheduling cost dominates |
| s09 viewer_fastapi | Serving precomputed regions over the network | Computing new regions on demand (deliberately out of scope) |

### The general principle

**Change what runs and how many copies of it run, not the code that consumes the output.** The Zarr-as-product invariant (§1) is what makes this possible — the renderer doesn't know which stage produced its input, so you can swap stages freely based on what the actual workload demands. That's the underlying reason for ten stages: they're not ten implementations of one thing, they're one contract with ten cost/benefit profiles.
