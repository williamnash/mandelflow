"""s08's per-frame compute is s06's — same kernel, same contract.

s08 is just s07's multi-frame loop running inside a cloud VM with the
output going to GCS instead of a local filesystem. The kernel is
unchanged; the deployment shape is what's new.
"""

from stages.s06_gpu_shader.compute import compute_frame

__all__ = ["compute_frame"]
