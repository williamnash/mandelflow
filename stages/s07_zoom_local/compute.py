"""s07's per-frame compute is s06's — same kernel, same contract.

The work that *makes* s07 a new stage lives in `run.py`: building the
schedule, holding a single GL context across many frames, and writing
a multi-frame Zarr. The kernel itself is unchanged.
"""

from stages.s06_gpu_shader.compute import compute_frame

__all__ = ["compute_frame"]
