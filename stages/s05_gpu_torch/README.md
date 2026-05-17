# Stage 05 — PyTorch on CUDA / MPS (float32)

**1.7s at 2048×2048, max_iter=512 on Apple MPS** — 10.4× over s00, but **slower than s03 and s04** on this hardware.

This is the stage whose wall-clock number is least flattering — and it's the most important one to read past the headline number on. s05 isn't about beating CPU on a laptop; it's about a fundamentally different execution model that scales to architectures we can't reach from CPU.

## What this stage does

Lifts the entire image onto the GPU as a few `(H, W)` tensors and performs one tensor op per iteration step. The GPU runs the same arithmetic across every pixel in parallel — no Python loop over pixels, no numba JIT, no Dask coordination.

```python
zr = torch.zeros_like(cr)               # (H, W) on GPU
zi = torch.zeros_like(ci)
out = torch.full(cr.shape, max_iter, dtype=torch.int32, device=device)

for k in range(max_iter):
    new_zi = 2.0 * zr * zi + ci         # one GPU op, all pixels
    new_zr = zr2 - zi2 + cr             # one GPU op, all pixels
    zr = torch.where(mask, new_zr, zr)
    zi = torch.where(mask, new_zi, zi)
    zr2 = zr * zr
    zi2 = zi * zi
    escaped = (zr2 + zi2 > 4.0) & mask
    out = torch.where(escaped, torch.full_like(out, k), out)
    mask = mask & ~escaped
```

## Float32, not complex64 — and why

Per CLAUDE.md invariant #6: stage 05 uses **separate float32 real and imaginary tensors**, not a single complex64 tensor.

- **MPS lacks complex-dtype support** historically. Going through float32-pair arithmetic lets the same code run on CUDA, MPS, and CPU torch backends without `PYTORCH_ENABLE_MPS_FALLBACK=1` games.
- **Float32 caps useful zoom at ~10⁶.** Deeper zooms need perturbation theory + reference-orbit math, which is stage 06's shader territory.

The cost is a small per-pixel divergence from s00's float64 reference. `test_cross_stage_equivalence.py` allows up to 5% pixels differing by ≤1 iteration count for s05; in practice the divergence is much smaller. You can see it as a slight visual softening at the set boundary compared to s00–s04 — same shape, slightly different escape counts within ±1 in a thin boundary band.

## Why s05 is slower than s03 / s04 on Apple Silicon

Three structural reasons:

1. **No per-pixel `break`.** On CPU, when a pixel escapes, its loop terminates (`break`). On GPU, all pixels run in SIMT lockstep — the loop iterates `max_iter` times regardless of how fast pixels escape. At the canonical full view, mean escape depth is ~30, so we're doing ~17× more work than s03 does for the same result.
2. **Per-op dispatch overhead on integrated MPS.** Apple Silicon's MPS backend has ~10s of µs of dispatch overhead per torch op. With 512 iterations × ~8 ops/iter, that's a few hundred ms of pure dispatch, even before any math runs.
3. **`torch.where` doesn't actually skip compute.** The mask preserves old `zr`/`zi` for escaped pixels but doesn't skip the FLOPs — the GPU still computes `new_zr` and `new_zi` for every pixel, then `where` picks which to keep. Saving compute via boolean indexing would require gather/scatter, which is its own performance hazard on GPU.

On a **discrete CUDA GPU**, all three of these pressures are different: massively more cores hide the dispatch overhead, and the brute-force tensor ops are exactly what CUDA cores are tuned for. The same code is expected to be ~10–20× faster on a T4 or A10 than on integrated MPS.

## Why s05 still matters

The pedagogical point isn't speed at 2048×2048 on one laptop — it's the **programming model**. Three properties of GPU tensor compute that no CPU stage has:

- **Linear scaling with image size.** s05 at 4096×4096 is ~4× the work of 2048×2048, and the GPU handles it without algorithmic changes. CPU stages start to feel memory-bound at the same scales.
- **Composable with the rest of the PyTorch ecosystem.** If someone wants to swap the Mandelbrot kernel for a learned implicit function or a differentiable renderer, the rest of the code is unchanged.
- **Direct path to s06 (the shader).** Stage 06 escapes the per-op dispatch ceiling entirely by collapsing the iteration loop into a single fragment shader. s05 is what makes the "yes, the GPU is involved" story plausible before s06 makes it fast.

## Cross-platform behaviour

- **Laptop (macOS, Apple Silicon):** `device = mps`, this benchmark.
- **CUDA node (GKE T4 / A10):** `device = cuda`, expected substantially faster.
- **CI hosts (no GPU):** `RuntimeError: Stage 05 requires a GPU (CUDA or MPS). Neither is available.` Tests skip via `pytest.mark.skipif(not has_gpu(), ...)`.
- **No torch installed at all:** module import fails cleanly; tests import-guard around s05 and skip with a single message.

## The shape break (still no hook in `_cli.py`)

s05 is the second stage with bespoke setup-then-compute in `run.py` (s04 was the first). Two examples isn't enough variety to design a hook system honestly — s04's setup is "open a `Client(LocalCluster())` context manager," s05's is "resolve a `torch.device` and pass it as a kwarg." These shapes are different enough that a single hook abstraction would force one to fit the other awkwardly. Will revisit at s06 (which needs an offscreen GL context — possibly close enough to s05's pattern that a hook makes sense).
