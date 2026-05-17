"""s09's per-frame compute is s06's — same kernel, same contract.

s09 takes s08's "ship s07 to one cloud machine" and scales it across many
machines by fanning frame ranges across a GKE cluster. Each Pod runs this
same `compute_frame` over its assigned range; the kernel doesn't know it's
running distributed.
"""

from stages.s06_gpu_shader.compute import compute_frame

__all__ = ["compute_frame"]
