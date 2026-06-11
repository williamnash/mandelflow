"""Stage 05: PyTorch on CUDA / MPS, float32 throughout.

GPU parallelism. The whole image lives as a few `(H, W)` tensors on
device; per-iteration work is `O(H*W)` tensor ops dispatched once,
which the GPU executes across thousands of cores.

Float32 constraint: real and imaginary parts are separate `float32`
tensors rather than a single `complex64`. This is for cross-platform
parity — MPS has historically been thin on complex-dtype support, and
the talk's deep-zoom story belongs to stage 06's shader anyway. The
float32 precision caps useful zoom at ~10⁶.

The active mask is a single boolean tensor; pixels that escape or are
caught by the cardioid / period-2 early-exits get masked out so they
no longer participate in the per-iteration arithmetic on the GPU.

Two variants of the same math live here:

- `compute_frame` — eager. Each iteration dispatches ~10 separate
  tensor ops through the Python API; per-op launch overhead dominates
  on small-to-medium frames. This *is* the stage's lesson.
- `compute_frame_compiled` — the fix. `torch.compile` (inductor)
  fuses each iteration's ops into one device kernel, so the loop pays
  one launch per iteration instead of ~10. Same arithmetic, same
  float32 story; only the dispatch changes. Requires torch >= 2.7 for
  inductor support on MPS. First call pays a one-off compile cost.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import torch

from common.store import ITERATIONS_DTYPE
from render.torch_device import get_torch_device


def _init_frame(
    center_re: float,
    center_im: float,
    width: float,
    resolution: int,
    max_iter: int,
    device: torch.device,
) -> tuple[torch.Tensor, ...]:
    """Shared setup: the c-plane grid, the early-exit mask, zeroed state."""
    half = width / 2.0
    x = torch.linspace(center_re - half, center_re + half, resolution,
                       dtype=torch.float32, device=device)
    y = torch.linspace(center_im - half, center_im + half, resolution,
                       dtype=torch.float32, device=device)
    cr, ci = torch.meshgrid(x, y, indexing="xy")

    cr_shift = cr - 0.25
    q = cr_shift * cr_shift + ci * ci
    in_cardioid = q * (q + cr_shift) < 0.25 * ci * ci
    cr_p1 = cr + 1.0
    in_period2 = cr_p1 * cr_p1 + ci * ci < 0.0625
    mask = ~(in_cardioid | in_period2)

    zr = torch.zeros_like(cr)
    zi = torch.zeros_like(ci)
    zr2 = torch.zeros_like(cr)
    zi2 = torch.zeros_like(ci)
    out = torch.full(cr.shape, max_iter, dtype=torch.int32, device=device)
    return cr, ci, mask, zr, zi, zr2, zi2, out


def _step(zr, zi, zr2, zi2, cr, ci, mask, out, k):
    new_zi = 2.0 * zr * zi + ci
    new_zr = zr2 - zi2 + cr
    zr = torch.where(mask, new_zr, zr)
    zi = torch.where(mask, new_zi, zi)
    zr2 = zr * zr
    zi2 = zi * zi
    escaped = (zr2 + zi2 > 4.0) & mask
    out = torch.where(escaped, k, out)
    mask = mask & ~escaped
    return zr, zi, zr2, zi2, mask, out


def compute_frame(
    center_re: float,
    center_im: float,
    width: float,
    resolution: int,
    max_iter: int,
    device: torch.device | None = None,
) -> np.ndarray:
    if device is None:
        device = get_torch_device()

    cr, ci, mask, zr, zi, zr2, zi2, out = _init_frame(
        center_re, center_im, width, resolution, max_iter, device
    )
    for k in range(max_iter):
        k_t = torch.tensor(k, dtype=torch.int32, device=device)
        zr, zi, zr2, zi2, mask, out = _step(zr, zi, zr2, zi2, cr, ci, mask, out, k_t)

    return out.cpu().numpy().astype(ITERATIONS_DTYPE)


@lru_cache(maxsize=1)
def _compiled_step():
    # dynamic=True: one compile serves every resolution, instead of a
    # recompile per frame size.
    return torch.compile(_step, dynamic=True)


def compute_frame_compiled(
    center_re: float,
    center_im: float,
    width: float,
    resolution: int,
    max_iter: int,
    device: torch.device | None = None,
) -> np.ndarray:
    if device is None:
        device = get_torch_device()

    cr, ci, mask, zr, zi, zr2, zi2, out = _init_frame(
        center_re, center_im, width, resolution, max_iter, device
    )
    step = _compiled_step()
    # The iteration counter stays on device: passing a fresh Python int
    # each pass would make dynamo specialise (recompile) per k value.
    k_t = torch.zeros((), dtype=torch.int32, device=device)
    one = torch.ones((), dtype=torch.int32, device=device)
    for _ in range(max_iter):
        zr, zi, zr2, zi2, mask, out = step(zr, zi, zr2, zi2, cr, ci, mask, out, k_t)
        k_t = k_t + one

    return out.cpu().numpy().astype(ITERATIONS_DTYPE)
