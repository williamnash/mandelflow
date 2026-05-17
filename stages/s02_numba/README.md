# Stage 02 — numba `@njit` over the per-pixel loop

**1.14s at 2048×2048, max_iter=512** — 15.5× over s00.

## What this stage does

Takes the exact triple loop from stage 00 and JIT-compiles it to native machine code via numba. The loop structure is unchanged; what changes is the executor underneath it.

```python
@njit(cache=True)
def _kernel(x, y, max_iter, out):
    resolution = out.shape[0]
    for i in range(resolution):
        for j in range(resolution):
            c = complex(x[j], y[i])
            z = 0 + 0j
            escape = max_iter
            for k in range(max_iter):
                z = z * z + c
                if abs(z) > 2:
                    escape = k
                    break
            out[i, j] = escape
```

## Why the jump is so large

Stage 00 spent ~95% of its time on Python interpreter overhead. Numba removes essentially all of it:

- The function compiles to LLVM IR, then to native code. Each statement becomes a few CPU instructions instead of an interpreted bytecode + object dispatch.
- Complex numbers become two adjacent doubles in registers; `z * z + c` is six float operations and an FMA.
- `range(max_iter)` becomes a plain counted loop with no iterator-object overhead.
- The `break` is preserved — we still get the per-pixel early exit that stage 01 couldn't have.

This stage isolates one specific cost: *the interpreter itself*. The math is identical to s00, byte for byte (see the cross-stage equivalence test — tolerance 0). All 15× of speedup comes from no longer asking Python to run the inner loop.

## What it tells you

When a Python-loop algorithm is CPU-bound on basic arithmetic and the inner work is small, `@njit` is the single highest-leverage change you can make. No code restructuring, no algorithmic insight — just a decorator.

## Caching

`cache=True` writes the compiled artifact under `__pycache__/`. First call after a clean checkout pays a ~1-2s compile cost; subsequent calls (even in fresh Python processes) reuse the cached binary. Tests run once-warm, so per-test compile cost is paid once per session.
