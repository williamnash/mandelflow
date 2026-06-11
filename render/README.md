# render/ — Zarr → pixels

Compute stages write the data product (iteration counts in Zarr/icechunk); everything that turns those counts into something you can look at lives here. Rendering is deliberately downstream — re-colour, re-crop, or re-encode without recomputing a single iteration (DESIGN.md: "replayable").

## The pipeline

```
iterations (frame, y, x) uint16          common.store.open_iterations_dataset
        │                                 (raw Zarr / icechunk, local / gs://)
        ▼
palettes.colorize  ──►  (H, W, 3) uint8 RGB
        │
        ├── frame.py      one frame → PNG        uv run python -m render.frame --input out/run.zarr
        └── animation.py  all frames → MP4       uv run python -m render.animation --input out/run.zarr
```

The stage-12 FastAPI viewer is a third consumer of the same `colorize` — stills, video, and the HTTP tile server agree pixel-for-pixel by construction.

## Module map

| Module | Role |
|---|---|
| `palettes.py` | The colour philosophy: cyclic palettes + √-count mapping (see its docstring — it's the most design-dense file here). Custom gradients `dusk` / `ultrafractal` / `ember`, plus blessed cyclic matplotlib builtins. |
| `frame.py` | Single frame → PNG. The "is my Zarr plausible?" tool. |
| `animation.py` | Frame stack → MP4 via PIL + ffmpeg. Pixel-perfect (no matplotlib canvas in the loop). |
| `gl_context.py` | Offscreen GL context factory: hidden pygame window on macOS, EGL standalone on Linux containers. Same shader both ways (CLAUDE.md invariant #5). Used by *compute* stage s06 — it lives here because it's display-stack plumbing, not kernel math. |
| `torch_device.py` | CUDA → MPS → clear one-line failure. Used by compute stage s05. |

## Why colours never flicker

`colorize` maps each pixel by `(√count × freq) mod 1` — a function of that pixel's own value only, with no per-frame or global normalisation. A pixel with the same iteration count is the same colour in frame 3 and frame 300, so animations are temporally stable for free. The trade-off (faint banding from integer counts) and the smooth-colouring path are documented in `palettes.py` and `docs/GOTCHAS.md`.
