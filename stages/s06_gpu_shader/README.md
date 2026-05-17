# Stage 06 — GLSL fragment shader on GPU

**0.06s at 2048×2048, max_iter=512 on Apple MPS** — 295× over s00, fastest stage at every resolution tested.

The architectural turning point. s06's wall-clock barely scales with image size because the entire iteration loop lives **inside one GPU dispatch** — no Python loop, no per-op CPU dispatch.

## Why s06 is structurally different from s05

| | s05 (PyTorch tensor ops) | s06 (fragment shader) |
|---|---|---|
| Iteration loop | Python `for k in range(max_iter)`, one tensor op per step | inside the shader, `for (int k = 0; k < u_max_iter; k++)` |
| Dispatches per frame | ~512 × 8 ≈ 4000 | **1** (one fullscreen quad draw) |
| Per-op CPU→GPU overhead | ~200–400 µs each (MPS) | paid once at draw time |
| GPU work per pixel | identical math | identical math |

The compute itself is the same. What changes is who runs the iteration loop: Python+torch dispatching ops one at a time vs. the GPU's own shader stage running the loop natively. On integrated GPUs with high dispatch overhead, that single difference is worth ~30×.

## What the shader actually is

A fragment shader is a small program the GPU runs once per pixel (once per "fragment") as part of the raster pipeline. We render a fullscreen quad — two triangles covering NDC `[-1, 1]²` — and the shader fires for every pixel inside that quad. Each invocation gets `gl_FragCoord` (the pixel position), computes its corresponding complex-plane coordinate, runs the full Mandelbrot iteration, and writes an `out float` value into the framebuffer.

```glsl
#version 410 core
out float f_escape;
uniform vec2  u_center;
uniform float u_width;
uniform vec2  u_resolution;
uniform int   u_max_iter;

void main() {
    // ... linspace-equivalent UV mapping ...
    // ... cardioid + period-2 early exits ...
    float zr = 0.0, zi = 0.0, zr2 = 0.0, zi2 = 0.0;
    for (int k = 0; k < u_max_iter; k++) {
        zi = 2.0 * zr * zi + ci;
        zr = zr2 - zi2 + cr;
        zr2 = zr * zr;
        zi2 = zi * zi;
        if (zr2 + zi2 > 4.0) { f_escape = float(k); return; }
    }
    f_escape = float(u_max_iter);
}
```

The result lives in an `R32F` texture (single-channel 32-bit float). CPU readback transfers `(H × W × 4)` bytes once and casts to `uint16` to match the canonical schema.

## Linspace-equivalent UV mapping

The default `gl_FragCoord` gives pixel-centre coordinates: `(0.5, 0.5)`, `(1.5, 0.5)`, … The naive shader UV would be `gl_FragCoord / u_resolution`, which is a half-pixel offset from `np.linspace(a, b, N)`. At 2048² with width 3.5 that's about `8.5e-4` off per pixel — enough to shift boundary pixels into different escape counts.

The shader computes `j = floor(gl_FragCoord.x)` (pixel index) and `u = j / (N - 1)` instead. Identical to numpy's linspace discretisation, so boundary divergence is float32-precision only, not grid-offset.

## Why we still have a `FASTMATH_STAGES`-level tolerance

s06 still runs in float32 and the GPU's `fma` semantics differ subtly from CPU IEEE-754 ordering. The cross-stage equivalence test allows 5% of pixels to differ by ≤1 iteration count against s00's float64 reference — same tolerance as s05. In practice the divergence is much smaller and visually indistinguishable.

The boundary detail in `out/s06_gpu_shader.png` looks slightly softer than s03/s04's PNGs (same as s05's) — that's the float32 / fma effect on iteration counts near the set boundary.

## Why this scales so flatly

| Resolution | s06 time | What's happening |
|---|---|---|
| 1024² | 0.05s | Driver / kernel launch dominates |
| 2048² | 0.06s | GPU starts doing real work |
| 4096² | 0.08s | Texture transfer becomes visible |

The GPU is parallelising over pixels by default — increasing resolution adds work but the cores absorb it. The fixed costs (context creation, shader compile, framebuffer setup, `glReadPixels` back to CPU) start to dominate at small resolutions; the gap closes at larger ones.

This shape is exactly the **opposite** of s05's. s05 pays per-op dispatch hundreds of times per call; s06 pays once. Same hardware, very different programming model.

## What this stage unlocks

The shader pattern is what makes **deep zoom** practical (the talk's stage-06 narrative). Float32 caps useful zoom at ~10⁶ via standard iteration; beyond that, the same shader scaffolding hosts **perturbation-theory** kernels (reference orbit + delta iteration in float32) to reach 10¹² and further. That second step is out of scope here, but the GL context, framebuffer, and readback path that would host it is what s06 just built.

## The shape break (same as s04 / s05)

s06's `run.py` is bespoke for the third time — GL context preflight via `has_gl()`, framebuffer lifecycle, pygame teardown. Each of s04, s05, and s06 has *different* setup needs (Dask cluster vs torch device vs GL context), so the temptation to write a single setup-hook abstraction is real but premature: any single hook design would force two of the three into an awkward fit. Three bespoke files is the honest cost.

## Cross-platform behaviour

- **macOS:** hidden pygame window, Apple OpenGL 4.1 → this bench.
- **Linux container:** Mesa EGL standalone context (`moderngl.create_standalone_context`) → same shader, same numbers (modulo driver differences).
- **No moderngl / pygame installed:** import-guarded; tests skip with one-line reason.
- **GL context can't be created (no drivers, etc.):** `has_gl()` returns False; CLI prints one clear line and exits.
