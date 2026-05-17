"""PyTorch device picker — CUDA → MPS → fail with a clear message.

Stage 05 implementations should use float32 throughout (separate real / imag
tensors, not complex dtypes) so the same code path works on CUDA, MPS, and
CPU without hitting MPS's historical complex-dtype gaps. Float32 caps useful
zoom at ~10^6; deep zoom lives in stage 06's shader.
"""

from __future__ import annotations


def get_torch_device():
    """Return a torch.device, or raise with a single clear line."""
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    raise RuntimeError(
        "Stage 05 requires a GPU (CUDA or MPS). "
        "Neither torch.cuda.is_available() nor torch.backends.mps.is_available() returned True."
    )
