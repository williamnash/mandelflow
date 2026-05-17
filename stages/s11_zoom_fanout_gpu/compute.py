"""s11's per-frame compute is s06's — same kernel, same contract.

s11 takes s10's "single cloud GPU VM" and scales it across many machines by
fanning frame ranges across a GKE cluster. Each Pod runs this same
`compute_frame` over its assigned range; the kernel doesn't know it's
running distributed.
"""

from stages.s06_gpu_shader.compute import compute_frame

__all__ = ["compute_frame"]
