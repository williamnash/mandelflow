"""s08's per-frame compute.

Currently delegates to **s03** (numba, single-thread, fastmath + early
exits) because the project's GPU quota request was denied and the VM
runs without an accelerator. Once the GPU quota is granted, swap this
import back to `stages.s06_gpu_shader.compute` to use the GLSL shader.
The rest of the stage (run.py, terraform, k8s) is unchanged either way.
"""

from stages.s03_numba_opt.compute import compute_frame

__all__ = ["compute_frame"]
