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
"""

from __future__ import annotations

import numpy as np
import torch

from common.store import ITERATIONS_DTYPE
from render.torch_device import get_torch_device


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

    for k in range(max_iter):
        new_zi = 2.0 * zr * zi + ci
        new_zr = zr2 - zi2 + cr
        zr = torch.where(mask, new_zr, zr)
        zi = torch.where(mask, new_zi, zi)
        zr2 = zr * zr
        zi2 = zi * zi
        escaped = (zr2 + zi2 > 4.0) & mask
        out = torch.where(escaped, torch.full_like(out, k), out)
        mask = mask & ~escaped

    return out.cpu().numpy().astype(ITERATIONS_DTYPE)
