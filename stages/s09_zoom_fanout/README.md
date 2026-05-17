# Stage 09 — Multi-machine fan-out on GKE

**Status: scaffold only.** Terraform skeleton + walkthrough; not provisioned, not pushed.

s09 takes s08's "ship s07 to one cloud machine" and scales it across **many machines** by fanning frame ranges across a GKE cluster. Same kernel (s06 shader) running in each Pod, same multi-frame Zarr written to GCS — what's different is **how many machines write to it in parallel**.

This is the stage where distributed compute earns its keep. It's also significantly more operational machinery than s08; only graduate here when single-machine throughput is actually the bottleneck.

## Frame range per Pod, not frame per Pod

A naive "one Pod per frame" mapping is wrong for our workload: per-Pod startup overhead (Pod schedule + image pull + Python imports + GL context creation) is ~15–50s; per-frame compute is ~5–10ms on a T4. That ratio is ~5,000:1 — startup would dominate everything.

s09 instead **batches a range of frames per Pod**. Each Pod is essentially s07's exact loop bounded to `[frame_start, frame_end)`. The GL context is created once per Pod and reused across all its frames. With 120 frames and 4 Pods, each Pod handles 30 frames in ~3s of real work, amortising its ~25s startup.

| Granularity | # Pods (120 frames) | Wall-clock (parallel) |
|---|---|---|
| 1 frame/Pod | 120 | ~5 min |
| **30 frames/Pod** | **4** | **~45s** |
| 60 frames/Pod | 2 | ~50s |

The `--n-pods` argument in `run.py` lets the dispatcher tune this; default of 4 is a reasonable starting point at 120 frames. For longer zooms (e.g., 1000 frames) you'd want ~10 Pods of ~100 frames each.

## What gets provisioned

| Resource | Purpose | Approx. cost |
|---|---|---|
| GKE **Standard** cluster | Control plane + node pools | ~$0.10/hr (zonal control plane) |
| `n1-standard-4` + **T4 GPU** node pool (multi-node) | Compute Pods run here | ~$0.40/hr per node |
| `e2-standard-2` node pool | Dagster control plane / IO Manager | ~$0.07/hr |
| **Artifact Registry** (shared with s08) | Docker image repo | pennies |
| **GCS bucket** (can reuse s08's) | `gs://<bucket>/runs/<id>.zarr` | pennies |
| **Workload Identity Federation** pool | OIDC trust: GitHub Actions → GCP | free |
| **Service Accounts** + IAM bindings | Pod → GCS via Workload Identity | free |

**Expected weekend cost: $8–12** with prompt teardown. GKE Standard (not Autopilot) — Autopilot abstracts away the node-pool primitives this stage exists to teach (see `docs/GOTCHAS.md` #7).

`terraform destroy` is the only safe path off the cost curve. **Set a phone alarm before `terraform apply`.**

## Credentials, in order

Three credential paths, vs s08's two — Workload Identity binding is the new one. Mid-step compared to running on a VM with an attached SA, but it's the right pattern for K8s.

### 1. Local Terraform / `gcloud`

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

ADC, no JSON keys.

### 2. CI / GitHub Actions → GCP (Workload Identity Federation)

`.github/workflows/deploy.yml` expects WIF secrets (`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SA`). The Terraform here provisions the WIF pool + provider + IAM bindings scoped to the GitHub repo. GitHub mints short-lived OIDC tokens; GCP swaps them for impersonation of `mandelflow-deploy@<project>.iam.gserviceaccount.com`. **No JSON keys.** See `docs/GOTCHAS.md` #6.

### 3. GKE Pods → GCS (Workload Identity binding)

The Kubernetes ServiceAccount `compute-sa` (in the `default` namespace) is bound to the GCP SA `mandelflow-compute@<project>.iam.gserviceaccount.com`. Pods using that KSA inherit `roles/storage.objectAdmin` on the Zarr bucket via the metadata server. Token exchange is automatic; no JSON keys live in any Pod.

**Zero static credentials anywhere in the system.**

## Deployment flow

```bash
# 0. Prerequisites: GCP project with billing enabled, T4 quota in your
#    region (file a quota request if you haven't already — usually
#    same-day approval).

# 1. Fill in tfvars
cp stages/s09_zoom_fanout/terraform/example.tfvars stages/s09_zoom_fanout/terraform/terraform.tfvars

# 2. Provision (~10 min for first apply — GKE cluster creation is slow)
cd stages/s09_zoom_fanout/terraform
terraform init
terraform apply -var-file=terraform.tfvars

# 3. Capture outputs into GitHub secrets and shell env
terraform output
gcloud container clusters get-credentials mandelflow --region <region>

# 4. Set up the K8s ServiceAccount with Workload Identity annotation
kubectl create serviceaccount compute-sa
kubectl annotate serviceaccount compute-sa \\
  iam.gke.io/gcp-service-account=mandelflow-compute@<project>.iam.gserviceaccount.com

# 5. Build and push the image
docker buildx build --platform linux/amd64 \\
  -t <region>-docker.pkg.dev/<project>/mandelflow/compute:dev .
docker push <region>-docker.pkg.dev/<project>/mandelflow/compute:dev

# 6. Fan out
python -m stages.s09_zoom_fanout.run \\
  --mode dispatch --n-pods 4 \\
  --n-frames 120 --resolution 1080 --max-iter 512 \\
  --output gs://<bucket>/runs/dev.zarr

# 7. Verify
gsutil ls gs://<bucket>/runs/dev.zarr/iterations/

# 8. TEAR IT DOWN
terraform destroy -var-file=terraform.tfvars
```

## Two execution paths

### Path A: Direct K8s Job submission (what `run.py` sketches)

The dispatcher builds the schedule, computes frame ranges, and submits one K8s Job per range using the `kubernetes` Python client. It polls Job status, surfaces failures, and exits when all Jobs complete. No Dagster dependency.

This is the path the local `dev/kind-cluster.yaml` validates — it spins up a CPU-only `kind` cluster on your laptop, so you can exercise the dispatch / submit / poll / retry logic without a real GKE bill or GPU.

### Path B: Dagster K8s executor (the architectural target)

The `iterations` asset in `orchestration/definitions.py` is partitioned by frame; Dagster's `k8s_job_executor` launches Pods automatically. The asset graph is unchanged from local Dagster runs — only the executor config and the `IOManager` change. Materialise via the Dagster UI or `dagster job execute`.

Path B requires:
- `orchestration/definitions.py` to exist (currently a known gap).
- `GCSIcechunkIOManager` — or raw Zarr region writes via `gcsfs` — for parallel-safe per-chunk writes. Icechunk is referenced in DESIGN.md §7 but the IOManager glue is itself unwritten (DESIGN.md §11).

## What lives in each subdirectory

```
stages/s09_zoom_fanout/
├── README.md          ← this file
├── compute.py         ← re-exports s06's compute_frame (same kernel)
├── run.py             ← --mode pod (per-Pod range entrypoint) +
│                        --mode dispatch (control-host fan-out)
├── terraform/         ← cluster, node pools, WIF, SAs, GCS bucket
├── k8s/               ← Pod / Job manifests
│   └── compute-pod.yaml
└── dev/               ← local kind cluster for plumbing tests
    └── kind-cluster.yaml
```

## Known gaps before this stage runs

In rough effort order:

1. **T4 GPU quota** in your project's region.
2. **`run.py` implementation** — both modes need filling in.
3. **`orchestration/definitions.py`** if you want Path B.
4. **`GCSIcechunkIOManager`** (or raw Zarr region writes) for parallel-safe per-chunk writes.
5. **`compute-pod.yaml`** template needs to be parameterised on `frame_start`/`frame_end` instead of `frame_index`.

The scaffolded files mark these with `# TODO(s09):` at the relevant spots.

## Why s09 still matters even when s08 is enough for the demo

s08 is sufficient for shipping a portfolio-grade Mandelbrot zoom video. s09 is the structural lesson:

- **Dask's `Client` + `dask.delayed` from s04 scales to a real cluster.** The same code pattern. Only the cluster connection changes.
- **Workload Identity (not API keys) is how production cloud compute talks to storage.**
- **Job-per-partition with right-sized partitions** is the canonical batch-compute pattern. Right-sizing is the engineering judgement.

If you're using this repo as a portfolio piece, s08 is what you demo; s09 is what you explain when someone asks "how would this scale?"

## Cost cautions

- **Cloud Load Balancers persist if you don't delete them.** None of these manifests create one — but be vigilant.
- **GPU node pools don't auto-scale down by default.** Tune `autoscaling { min_node_count = 0 }` in `gke.tf` if you want cluster-autoscaler to shrink between runs.
- **Always run `terraform destroy`.** Reapplying is cheap; an idle GPU pool overnight is not.
