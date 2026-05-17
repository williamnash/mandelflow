# Stage 03 — numba `@vectorize` with fastmath + early exits (single-threaded)

**0.12s at 2048×2048, max_iter=512** — 148× over s00, **9.4× over s02**.

This stage isolates **kernel-level** optimisations — no parallelism. The story across stages is one optimisation per stage; s04 adds the parallelism dimension on top of this kernel.

## The decorator

```python
@vectorize(
    ["uint16(complex128, int64)"],
    nopython=True,
    fastmath=True,
    cache=True,
)
def _instability(c, max_iter):
    ...
```

Note the **absence** of `target="parallel"`. Numba's default `target="cpu"` is single-threaded. We deliberately give up the in-process prange here because s04 will fan this same kernel across worker *processes* via Dask — and if both layers parallelised, we'd end up with nested parallelism oversubscribing cores. One optimisation per stage; parallelism lives in s04.

## What this stage adds

### `fastmath=True`

Relaxes IEEE-754 ordering rules so the compiler can:

- Reassociate `(a*b) + c` into a single fused multiply-add (FMA) instruction.
- Reorder reductions for SIMD vectorisation within a single thread.
- Skip NaN / signed-zero edge cases on float compares.

For Mandelbrot iteration, this lets each pixel's inner loop saturate the SIMD pipeline within one core. **Cost:** a small per-pixel divergence from s00 near the set boundary — one or two pixels per thousand may differ by one iteration count. That's why s03 is in `FASTMATH_STAGES` rather than `EXACT_STAGES`.

### Cardioid + period-2 early exits

The Mandelbrot set's two largest features have closed-form membership tests:

- **Cardioid** (`|c - 1/4| - 1/2 < 0` derivative test): the big bulb open to the right. About a third of the set's area.
- **Period-2 bulb** (`|c + 1| < 1/4`): the disk centred at -1. About 1/16 of the area.

```python
cr_shift = cr - 0.25
q = cr_shift * cr_shift + ci * ci
if q * (q + cr_shift) < 0.25 * ci * ci:
    return max_iter         # in cardioid
cr_p1 = cr + 1.0
if cr_p1 * cr_p1 + ci * ci < 0.0625:
    return max_iter         # in period-2 bulb
```

For points known by closed form to be in the set, we skip iteration entirely. These are the points that *should* burn the full `max_iter` budget under naive iteration — so skipping them eliminates the largest chunk of compute.

### Squared-magnitude escape test

```python
if zr * zr + zi * zi > 4.0:    # vs.  if abs(z) > 2.0
```

`abs(z)` calls `sqrt`, which is expensive. `zr² + zi² > 4` gives the same result without the sqrt. Combined with the complex multiplication unrolled into real arithmetic, the inner loop runs purely on adds and multiplies — exactly what SIMD pipelines and FMA want.

## What this stage proves

Even a single thread can be ~9× faster than plain JIT when you let the compiler use fastmath and you give it algorithmic insight (early exits). The interpreter cost was the *first* mountain (s02). Per-element math quality is the *second* mountain. Parallelism is a separate axis still ahead.

## Tolerance against s00

Because of `fastmath`, s03 matches s00 within `assert_iterations_close` defaults: ≤1% of pixels may differ by ≤1 iteration count. In practice the divergence is far smaller; the visual output is indistinguishable from s00's. See `tests/integration/test_cross_stage_equivalence.py`.
