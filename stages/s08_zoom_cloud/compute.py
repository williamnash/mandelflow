"""s08's per-frame compute is s06's — same kernel, same contract.

The architecture lesson of s08 is *where* the computation runs (one Pod per
frame on a GKE GPU node, writing to a GCS-backed Zarr), not what kernel runs
inside each Pod. Just like s07, the work that makes this a distinct stage
lives in `run.py` and in the surrounding infrastructure (`terraform/`,
`k8s/`).
"""

from stages.s06_gpu_shader.compute import compute_frame

__all__ = ["compute_frame"]
