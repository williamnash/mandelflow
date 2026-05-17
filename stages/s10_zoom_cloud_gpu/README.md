# Stage 10 — Single cloud machine, GPU kernel

**Status: placeholder.** Named but not implemented.

## What this stage would be

s10 is the GPU-enabled counterpart of [s08](../s08_zoom_cloud_cpu/) — same "one cloud machine running s07's loop" shape, but with a GPU attached and the s06 fragment-shader kernel. The diff against s08 is small and mechanical:

- `terraform/vm.tf`: add a `guest_accelerator { type = "nvidia-tesla-t4"; count = 1 }` block, change `machine_type` to `n1-standard-4`, set `scheduling.on_host_maintenance = "TERMINATE"`, swap the COS image for `projects/deeplearning-platform-release/global/images/family/common-cu129-ubuntu-2204-nvidia-580` (Deep Learning VM with CUDA + Docker preinstalled).
- `compute.py`: import from `stages.s06_gpu_shader.compute` instead of `stages.s03_numba_opt.compute`.
- `run.py`: add the GL-context acquisition (`make_offscreen_context`) and pass `ctx=` into the per-frame call — matches the pattern in `stages/s07_zoom_local/run.py`.

The rest (SA, IAM bindings, bucket, AR, budget, firewall) is shared with s08 and doesn't need re-provisioning.

## Why it's not implemented today

The `mandelflow-2026` project was rejected for `GPUS_ALL_REGIONS` quota on 2026-05-17 (new-project policy: "wait 48h or until billing has more history"). Rather than mutate s08 to be GPU-then-CPU-then-GPU-again as quota state shifts, the CPU and GPU single-VM paths live as separate sibling stages.

## When this gets built

Three triggers, any of which justifies implementing this directory:

1. **GCP quota is granted.** Resubmit the quota request after 48h or once the billing account has more history. If approved, this stage is a ~30-min port of s08's structure with the diffs above.
2. **Multi-cloud GPU work.** Both AWS (`g4dn.xlarge` with a T4) and Azure (NC-series with T4/V100) offer T4 GPUs without GCP's new-project quota dance. If GCP stays blocked, this directory becomes the spot for an AWS/Azure single-GPU-VM Terraform module instead — same shape, different provider.
3. **You want to demo the GPU stack live.** Cloud Run Jobs with GPUs (L4) is a serverless option without long-lived VM management. Worth considering if quota remains the persistent blocker.

## Naming convention

The cloud progression in this repo is a 2×2 of two axes: **machine count** × **compute type**.

|  | CPU | GPU |
|---|---|---|
| Single | [s08](../s08_zoom_cloud_cpu/) | **s10** (this stage) |
| Many | [s09](../s09_zoom_fanout_cpu/) | [s11](../s11_zoom_fanout_gpu/) |

Each stage adds exactly one axis over the simpler version. s10 adds GPU to s08; s11 adds machine count to s10.
