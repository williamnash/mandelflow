# Stage 04 — Dask intra-frame tile fan-out

**3.00s at 2048×2048, max_iter=512** — 5.9× over s00.

The first stage where the wall-clock number goes *backward* relative to s03 (0.05s), and that's the point. s04 is the **architecture stage** — its value is what comes next, not what it does on a single laptop.

## What this stage does

Tiles the image into `n_tiles × n_tiles` blocks (4×4 = 16 by default) and dispatches each block as a `dask.delayed` task. A `LocalCluster` of 4 worker *processes* picks them up in parallel.

```python
# stages/s04_dask_local/compute.py
for ti in range(n_tiles):
    for tj in range(n_tiles):
        y_slice = y[boundaries[ti]:boundaries[ti + 1]]
        x_slice = x[boundaries[tj]:boundaries[tj + 1]]
        tasks.append(dask.delayed(_compute_tile)(x_slice, y_slice, max_iter))

results = dask.compute(*tasks)
```

The per-tile kernel is **s01's vectorised numpy code**, inlined. We deliberately did *not* use s02 or s03 underneath — the goal is to isolate "fan tiles across worker processes" as the only new variable. Whatever speedup s04 shows over s01 is attributable to Dask alone.

## Why it's slower than s02 / s03

| | s02 | s03 | s04 |
|---|---|---|---|
| Per-pixel kernel | native JIT, single thread | native JIT, parallel, fastmath | numpy mask loop |
| Parallelism | none | numba `prange` (in-process threads) | Dask (worker processes) |
| Coordination cost | none | ~µs (thread pool) | ~ms (cluster spinup, serialisation) |

Process-based fan-out has higher coordination overhead than intra-process threading: every tile's input arrays serialise across the worker boundary, and the cluster itself takes ~200ms to spin up. On a 2048×2048 single frame, that overhead is a noticeable fraction of total time. On a single laptop, s03's in-process parallel JIT wins.

## Why s04 still matters

The pattern `with Client(cluster): dask.compute(*tasks)` is the same shape that will dispatch work **across machines** in stage 07 (a Dask cluster on a private network) and stage 08 (a Kubernetes-managed cluster on GKE). When we move from "16 tiles on one laptop" to "500 frames across 50 K8s pods," `dask.delayed` and `dask.compute` are unchanged — only the cluster connection string differs.

## The shape break

s04 is the first stage that doesn't fit the `run_single_frame_stage` template — it needs to open a `LocalCluster` + `Client` context outside `compute_frame`. Rather than retrofitting hooks into `_cli.py` for one example, s04's `run.py` is a deliberate one-off. If s05 (GPU/torch) and s06 (GL shader) end up wanting the same setup-then-compute shape, that's two more examples worth informing a `_cli.py` hook design from.

## Why bit-identical to s01

Each tile receives a *slice* of the global linspace, not a re-computed linspace from a tile centre + tile width. That means the float values entering each tile's kernel are *exactly* what s01's kernel would have seen at the same pixel positions. Same floats in, same escape counts out. The cross-stage equivalence test catches any drift here at tolerance 0.
