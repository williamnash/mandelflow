# Stage 04 — Dask intra-frame tile fan-out

**0.07s at 2048×2048, max_iter=512** — 253× over s00, 1.7× over s03.

The **parallelism** stage. Same kernel as s03 (kept single-threaded for exactly this reason), now fanned across worker *processes* via Dask.

## What this stage does

Tiles the image into `n_tiles × n_tiles` blocks (4×4 = 16 by default) and dispatches each block as a `dask.delayed` task. A `LocalCluster` of 4 worker processes picks them up in parallel.

```python
# stages/s04_dask_local/compute.py
from stages.s03_numba_opt.compute import _instability

def _compute_tile(x_slice, y_slice, max_iter):
    X, Y = np.meshgrid(x_slice, y_slice)
    C = X + 1j * Y
    return _instability(C, max_iter)        # ← reuses s03's JIT kernel

# Inside compute_frame:
tasks = []
for ti in range(n_tiles):
    for tj in range(n_tiles):
        tasks.append(dask.delayed(_compute_tile)(x_slice, y_slice, max_iter))
results = dask.compute(*tasks)
```

s04's contribution is purely the parallelism layer. Whatever speedup we see over s03 is attributable to Dask alone — the per-pixel math is identical.

## Why we reuse s03's kernel

If each worker also used numba's `target="parallel"`, every Dask worker process would fork its own thread pool inside numba. On an 8-core laptop with 4 workers × 8 threads each = 32 OS threads competing for 8 cores. The OS thrashes; both layers get less than their fair share. **One optimisation per stage** isn't just a pedagogical choice — it's the correct system design.

s03 stays single-threaded, s04 adds the process-level parallelism. Clean layering.

## Why it's faster than s03

| | s03 | s04 |
|---|---|---|
| Kernel | numba @vectorize, fastmath, early exits | same |
| Parallelism | single thread | 4 worker processes |
| Coordination cost | none | ~ms (Dask task graph + serialisation) |

At 2048×2048 the work per tile (~0.03s) is comfortably above Dask's coordination overhead, so the 4-way parallelism wins. For tiny resolutions the overhead would dominate — which is why `compute_frame` falls back to `n_tiles=1` when the resolution is small (tests at resolution=1 use the synchronous scheduler, no cluster).

## Why s04 still matters beyond perf

The pattern `with Client(cluster): dask.compute(*tasks)` is the same shape that will dispatch work **across machines** in stage 07 (frames fanned across a Dask cluster) and stage 08 (a Kubernetes-managed cluster on GKE). When we move from "16 tiles on one laptop" to "500 frames across 50 K8s pods," `dask.delayed` and `dask.compute` are unchanged — only the cluster connection string differs.

s04 is the architecture stage that makes the cloud stages possible.

## The shape break

s04 is the first stage that doesn't fit `stages._cli.run_single_frame_stage` — it needs to open a `LocalCluster` + `Client` context outside `compute_frame`. Its `run.py` is bespoke. If s05 / s06 want a similar setup-then-compute shape (GPU device acquisition, GL context), we'll have two examples to inform a `_cli.py` hook design from. Until then, one bespoke file is the right cost.

## Bit-equivalence

Each tile receives a *slice* of the global linspace, not a re-computed linspace from a tile centre + tile width. That means the float values entering each tile's kernel are *exactly* what s03's kernel would have seen at the same pixel positions. s04 is bit-identical to s03 — same `_instability` calls, same numbers. Tolerance against s00 comes from s03's fastmath; s04 inherits the same `FASTMATH_STAGES` tolerance.
