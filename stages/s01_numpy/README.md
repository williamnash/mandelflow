# Stage 01 — Vectorised numpy with mask-tracked escapes

**10.87s at 2048×2048, max_iter=512** — 1.6× over s00.

## What this stage does

Replaces the per-pixel Python loop with array-wide numpy operations. A boolean `mask` tracks which pixels are still iterating; each numpy call updates only the unescaped pixels.

```python
Z = np.zeros_like(C)
out = np.full(C.shape, max_iter, dtype=ITERATIONS_DTYPE)
mask = np.ones(C.shape, dtype=bool)

for k in range(max_iter):
    Z[mask] = Z[mask] * Z[mask] + C[mask]
    escaped = np.abs(Z) > 2
    newly_escaped = escaped & mask
    out[newly_escaped] = k
    mask &= ~escaped
```

## Why the speedup is modest

This is the surprising stage — most people expect 10×, see <2×, and wonder what went wrong.

Two effects fight each other:

- **Numpy wins on per-element overhead.** The inner work (`z*z + c`) executes in compiled C, not interpreted Python. For each iteration, it's much faster *per pixel*.
- **Numpy loses on early-exit asymmetry.** Stage 00's `break` skips remaining iterations for any pixel that has already escaped. Stage 01 can't `break` per-pixel inside a numpy expression — it has to step the *entire* unescaped mask through `max_iter` iterations. Fancy-indexed assignment (`Z[mask] = ...`) also isn't free.

Net: per-iteration speed-up × per-pixel slowdown ≈ 1.6×. The numpy version pulls further ahead as `max_iter` grows (fewer pixels escape early relative to the iteration budget) or as resolution grows (numpy's per-call overhead amortises better).

## What this stage proves

Vectorisation alone is not enough when the algorithm has per-element early-exit behaviour. We need either:

- A code generator that compiles per-pixel Python loops *and* keeps early-exit (→ stage 02 with `@njit`), or
- A target where parallelism is cheap enough that we can afford to iterate every pixel to `max_iter` (→ GPU stages).
