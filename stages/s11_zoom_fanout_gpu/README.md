# Stage 11 — Multi-machine fan-out on GKE, GPU kernel

**Status: scaffold only.** Architecture documented; not provisioned, not pushed.

s11 takes [s10](../s10_zoom_cloud_gpu/)'s "single cloud GPU VM" and scales it across **many machines** by fanning frame ranges across a GKE cluster. Same kernel (s06 shader) running in each Pod, same multi-frame Zarr written to GCS — what changes is **how many machines write to it in parallel**.

This is the stage where distributed compute earns its keep. It's also significantly more operational machinery than s10; only graduate here when single-machine throughput is actually the bottleneck.

## Infrastructure is owned by s09

The GKE cluster, CPU node pool, Workload Identity pool, runtime SA, and deploy SA are all provisioned by **`stages/s09_zoom_fanout_cpu/terraform/`**. s11 is not a separate cloud foundation — it's the *same* cluster with the GPU node pool turned on:

```hcl
# stages/s09_zoom_fanout_cpu/terraform/terraform.tfvars
gpu_node_count   = 1                  # was 0 for s09
gpu_machine_type = "n1-standard-4"    # carries one T4
zone             = "us-central1-a"    # must have T4 quota
```

Then re-apply that terraform. Only one new resource is created — `google_container_node_pool.gpu_pool[0]` — and it's tainted `nvidia.com/gpu=present:NoSchedule` so non-GPU Pods can't accidentally land on it.

This stage has no `terraform/` directory of its own on purpose: the infra story is "share the s09 cluster; add the GPU pool when you need it." Two terraform dirs that reference each other would teach the wrong lesson.

## Frame range per Pod, not frame per Pod

A naive "one Pod per frame" mapping is wrong for our workload: per-Pod startup overhead (Pod schedule + image pull + Python imports + GL context creation) is ~15–50s; per-frame compute is ~5–10ms on a T4. That ratio is ~5,000:1 — startup would dominate everything.

s11 instead **batches a range of frames per Pod**. Each Pod is essentially s07's exact loop bounded to `[frame_start, frame_end)`. The GL context is created once per Pod and reused across all its frames. With 120 frames and 4 Pods, each Pod handles 30 frames in ~3s of real work, amortising its ~25s startup.

| Granularity | # Pods (120 frames) | Wall-clock (parallel) |
|---|---|---|
| 1 frame/Pod | 120 | ~5 min |
| **30 frames/Pod** | **4** | **~45s** |
| 60 frames/Pod | 2 | ~50s |

Dagster's `k8s_job_executor` with `max_concurrent: 16` plus a partition range covering all frames realises this — each in-flight partition is one Pod, each Pod processes its partition's frame range.

## What gets provisioned (delta vs s09)

| Resource | Created by | Approx. cost |
|---|---|---|
| GKE Standard cluster | s09 terraform | ~$0.10/hr (zonal control plane) |
| `e2-standard-2` CPU pool | s09 terraform | ~$0.07/hr |
| `n1-standard-4` + **T4 GPU** pool | s09 terraform (`gpu_node_count > 0`) | ~$0.40/hr per node |
| Workload Identity Federation pool | s09 terraform | free |
| Compute / deploy SAs | s09 terraform | free |
| Artifact Registry, GCS bucket | s08 terraform | pennies |

**Expected weekend cost: $8–12** with prompt teardown. GKE Standard (not Autopilot) — Autopilot abstracts away the node-pool primitives this stage exists to teach (see `docs/GOTCHAS.md` #7).

Teardown: bump `gpu_node_count` back to 0 and re-apply s09's terraform. The GPU pool is destroyed; the cluster lingers (still costs the zonal control-plane $0.10/hr). To remove the cluster entirely, `terraform destroy` in s09.

**Set a phone alarm before `terraform apply`.**

## Credentials, in order

Three credential paths, vs s08/s10's two — Workload Identity binding is the new one.

### 1. Local Terraform / `gcloud`

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

ADC, no JSON keys.

### 2. CI / GitHub Actions → GCP (Workload Identity Federation)

`.github/workflows/deploy.yml` expects WIF secrets (`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SA`). s09's terraform provisions the WIF pool + provider + IAM bindings scoped to the GitHub repo. GitHub mints short-lived OIDC tokens; GCP swaps them for impersonation of `mandelflow-deploy@<project>.iam.gserviceaccount.com`. **No JSON keys.** See `docs/GOTCHAS.md` #6.

### 3. GKE Pods → GCS (Workload Identity binding)

The Kubernetes ServiceAccount `compute-sa` (in the `default` namespace) is bound to the GCP SA `mandelflow-compute@<project>.iam.gserviceaccount.com`. Pods using that KSA inherit `roles/storage.objectAdmin` on the Zarr bucket via the metadata server. Token exchange is automatic; no JSON keys live in any Pod.

**Zero static credentials anywhere in the system.**

## Deployment flow

```bash
# 0. Prerequisites: GCP project with billing enabled, s08's terraform applied
#    (provides bucket + AR + project APIs), T4 quota in your region.

# 1. If you haven't already brought up the cluster for s09, do so now —
#    same terraform, just with gpu_node_count > 0.
cd stages/s09_zoom_fanout_cpu/terraform
# edit terraform.tfvars: set gpu_node_count = 1
terraform apply -var-file=terraform.tfvars

# 2. Cluster credentials + KSA setup
gcloud container clusters get-credentials mandelflow --region us-central1
kubectl create serviceaccount compute-sa 2>/dev/null || true
kubectl annotate serviceaccount compute-sa --overwrite \
  iam.gke.io/gcp-service-account=$(terraform output -raw compute_service_account)

# 3. Build + push image (BuildKit, registry-backed cache)
cd ../../..
gcloud builds submit --config cloudbuild.yaml --region us-central1 .

# 4. Fan out via Dagster's k8s_job_executor → GPU pool
MANDELFLOW_EXECUTOR=k8s_gpu \
MANDELFLOW_KERNEL=gpu_shader \
MANDELFLOW_STORAGE=icechunk \
MANDELFLOW_ICECHUNK_PATH=gs://<bucket>/runs/s11.icechunk \
uv run dagster asset materialize \
  --module-name orchestration.definitions \
  --select iterations --partition-range 0000...0119

# 5. Verify
gsutil ls gs://<bucket>/runs/s11.icechunk/

# 6. TEAR IT DOWN
cd stages/s09_zoom_fanout_cpu/terraform
# edit terraform.tfvars: set gpu_node_count = 0 (keeps the cluster for s09)
# OR: terraform destroy to remove everything
terraform apply -var-file=terraform.tfvars
```

## How the `k8s_gpu` executor scheduling works

`orchestration/definitions.py::_k8s_executor(gpu=True)` injects, for every Pod Dagster launches:

- `nodeSelector` / toleration: `nvidia.com/gpu=present:NoSchedule` — matches the taint on the GPU pool nodes so Pods schedule onto T4 hardware.
- Resource request: `nvidia.com/gpu: 1` — the GKE device plugin claims one T4 and mounts the CUDA / NVIDIA libs into the Pod.
- `serviceAccountName: compute-sa` — picks up Workload Identity → GCS via the metadata server.
- `imagePullPolicy: Always` — guarantees the latest tag, since we don't yet pin per-run.
- Forwarded env vars: every `MANDELFLOW_*` from the local Dagster process so the Pod boots with the same kernel/storage/schedule.

The asset graph (`iterations`) is unchanged from local runs. Only the executor + IOManager flips via env var.

## Known gaps before this stage runs

In rough effort order:

1. **T4 GPU quota** in your project's region.
2. **`run.py` implementation** if you want Path A (direct K8s Job submission via the `kubernetes` client) instead of the Dagster path. Path B (Dagster `k8s_job_executor`) is implemented and validated against the matrix in `orchestration/definitions.py`.
3. **Verify image has the GL/CUDA stack.** The current `Dockerfile` is multi-stage CUDA + Mesa EGL — should be fine, but s06 (`gpu_shader`) needs an EGL context inside the Pod. The first Pod will tell us.

## Why s11 still matters even when s10 is enough for the demo

s10 (a single GPU VM) is sufficient for shipping a portfolio-grade Mandelbrot zoom video. s11 is the structural lesson:

- **Dask's `Client` + `dask.delayed` from s04 scales to a real cluster.** The same code pattern. Only the cluster connection changes.
- **Workload Identity (not API keys) is how production cloud compute talks to storage.**
- **Job-per-partition with right-sized partitions** is the canonical batch-compute pattern. Right-sizing is the engineering judgement, and 30 frames/Pod here is exactly that judgement.

If you're using this repo as a portfolio piece, s10 is what you demo; s11 is what you explain when someone asks "how would this scale?"

## Cost cautions

- **Cloud Load Balancers persist if you don't delete them.** None of these manifests create one — but be vigilant.
- **GPU node pools don't auto-scale down by default.** Tune `autoscaling { min_node_count = 0 }` in `gke.tf` if you want cluster-autoscaler to shrink between runs.
- **`gpu_node_count = 0` + re-apply** is the cheap teardown — keeps the cluster but drops the GPU bill. Full `terraform destroy` is the only way to zero the control-plane cost.
