# Stage 03 — numba `@vectorize` + fastmath + parallel + early exits

**0.05s at 2048×2048, max_iter=512** — **354×** over s00, **22.8× over s02**.

The largest single-stage jump in the CPU progression. Four stacked optimisations on top of s02.

## The decorator does a lot of work

```python
@vectorize(
    ["uint16(complex128, int64)"],
    nopython=True,
    fastmath=True,
    cache=True,
    target="parallel",
)
def _instability(c, max_iter):
    ...
```

Three of those kwargs are speedups:

### `target="parallel"`

Numba compiles the function as a ufunc and parallelises it across CPU cores via a `prange` under the hood. Mandelbrot is embarrassingly parallel (every pixel is independent), so scaling is near-linear with core count. On an 8-core laptop this alone accounts for ~6-7× of the speedup over s02.

### `fastmath=True`

Relaxes IEEE-754 ordering rules. The compiler is now free to:

- Reassociate `(a*b) + c` into a single fused multiply-add (FMA) instruction.
- Reorder reductions for SIMD vectorisation.
- Skip NaN / signed-zero edge cases on float compares.

For Mandelbrot iteration, this lets each pixel's inner loop saturate the SIMD pipeline. Net: ~2× over plain `@njit`. **Cost:** a small per-pixel divergence from s00 near the set boundary — one or two pixels per thousand may differ by one iteration count. That's why s03 is the first entry in `FASTMATH_STAGES` (relaxed tolerance against s00).

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

For points known by closed form to be in the set, we skip iteration entirely and return `max_iter` immediately. These are the points that *should* burn the full iteration budget under naive iteration, so the savings are large. A few floating-point ops replace hundreds of complex multiplications.

### Squared-magnitude escape test

```python
if zr * zr + zi * zi > 4.0:    # vs.  if abs(z) > 2.0
```

`abs(z)` calls `sqrt`, which is expensive. `zr² + zi² > 4` gives the same result with one fewer sqrt per pixel per iteration. Combined with the complex multiplication unrolled into real arithmetic, the inner loop runs purely on adds and multiplies — exactly what SIMD pipelines and FMA want.

## Why it's the last CPU stage

s03 is essentially "all the CPU optimisations stacked." The next jump is **architectural**, not compiler-level — stage 04 (Dask local cluster) and onward use process / device / cluster parallelism, not better instruction-level work per pixel.

## Tolerance note

Because of `fastmath`, s03 matches s00 within `assert_iterations_close` defaults: ≤1% of pixels may differ by ≤1 iteration count. In practice the divergence is far smaller; the visual output is indistinguishable from s00's. See `tests/integration/test_cross_stage_equivalence.py`.
