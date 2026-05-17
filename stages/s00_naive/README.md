# Stage 00 — Naive Python triple loop

**17.68s at 2048×2048, max_iter=512** — the baseline every other stage measures against.

## What this stage does

The textbook Mandelbrot implementation: three nested Python `for` loops, one complex multiplication per inner-loop body, exit early on escape.

```python
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

## Why it's slow

Every operation in the inner loop pays the CPython interpreter tax:

- `z * z + c` invokes Python's complex `__mul__` and `__add__` methods — dispatched through `PyObject_Type` lookups, object creation for each intermediate, reference counting.
- `abs(z) > 2` constructs a Python float, calls `__abs__`, compares.
- The `for k in range(max_iter)` loop itself dispatches a bytecode opcode per step.

For a 2048×2048 grid with average escape depth of ~50 iterations, that's roughly 2×10⁸ object allocations on the hot path. The CPU is barely doing math — it's mostly shuffling Python objects.

## Why it's not catastrophic

The `break` on escape means we don't iterate the full `max_iter` budget per pixel — most pixels escape in <50 iterations. Stage 01 (vectorised numpy) doesn't get the same short-circuit benefit, which is why its speedup is more modest than you'd expect.

## Pedagogical note

This stage exists deliberately. Every "obvious optimisation" we *don't* make here (squared magnitude instead of `abs`, preallocating `c`, etc.) is a teaching opportunity that some later stage gets to claim.
