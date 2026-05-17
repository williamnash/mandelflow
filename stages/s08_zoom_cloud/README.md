# Stage 08 — Cloud-distributed multi-frame zoom

**Status: scaffold only.** This stage isn't runnable yet. The Terraform, Pod manifests, and `run.py` here are stubs that show the deployment shape; they'll need filling in before they touch real infrastructure.

s08 takes s07's multi-frame zoom and fans the frames across a Kubernetes cluster on GKE. Same kernel as s06 (and s07), same per-frame contract — what changes is the *executor*: each frame becomes one Pod on a GPU node, and the Pods write per-frame chunks to a single GCS-backed Zarr store. This is where Dask / Dagster's partition fan-out earns its keep — multi-machine throughput, not just multi-core.

## What gets provisioned

| Resource | Purpose | Approx. cost |
|---|---|---|
| GKE **Standard** cluster | Control plane + node pools | ~$0.10/hr (zonal control plane) |
| `n1-standard-4` + **1× T4 GPU** node pool | Where compute Pods run | ~$0.40/hr per node |
| `e2-standard-2` node pool | Dagster control plane, IO Manager | ~$0.07/hr |
| **Artifact Registry** repository | Hosts the mandelflow Docker image | pennies |
| **GCS bucket** | The `gs://<bucket>/runs/<run_id>.zarr` artifact | pennies for typical runs |
| **Workload Identity Federation** pool | OIDC trust between GitHub Actions and GCP | free |
| **Service Account** + IAM bindings | Pod → GCS access via Workload Identity | free |

**Expected weekend cost: $8–12** if you tear down the GPU pool promptly. Use Autopilot — wait, no, *don't* use Autopilot. Use Standard. GKE Autopilot abstracts away the GPU node pool primitives this stage exists to teach (see `docs/GOTCHAS.md` #7).

`terraform destroy` is the only safe path off the cost curve. **Set a phone alarm before `terraform apply`.**

## Credentials, in order

> Your "Google API key" isn't what this needs. API keys authenticate client requests to public Google APIs (Maps, Translate, the Gemini API). For provisioning GCP infrastructure and running workloads in it you need different credential types — listed below in the order you'll use them.

### 1. Local Terraform / `gcloud` (you, on your laptop)

```bash
gcloud auth login                         # interactive — opens browser
gcloud auth application-default login     # for Terraform / Python SDKs
gcloud config set project YOUR_PROJECT_ID
```

This uses **your user identity**. Terraform reads Application Default Credentials (ADC) from `~/.config/gcloud/application_default_credentials.json`. No JSON keys to manage.

### 2. CI / GitHub Actions → GCP (Workload Identity Federation)

The repo's `.github/workflows/deploy.yml` already expects WIF secrets (`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SA`). The Terraform here provisions the WIF pool + provider + IAM bindings that trust the GitHub OIDC issuer. **No static service-account JSON keys** — GitHub mints short-lived tokens, GCP swaps them for impersonation of the deploy SA. See `docs/GOTCHAS.md` #6.

### 3. GKE Pods → GCS (Workload Identity binding)

The compute Pods need to read/write the Zarr store. They authenticate via **Workload Identity** — the Kubernetes Service Account `compute-sa` is bound to the GCP Service Account `mandelflow-compute@<project>.iam.gserviceaccount.com`, which has `roles/storage.objectAdmin` on the Zarr bucket. Pods get short-lived tokens from the GKE metadata server. **Still no JSON keys.**

The whole stage runs on zero static credentials. Every long-lived secret is replaced by IAM bindings.

## Deployment flow (when you come back to actually do this)

```bash
# 0. Prerequisites: a GCP project with billing enabled, you have Owner or
#    sufficient IAM admin role on it.

# 1. Copy the example tfvars and fill it in
cp stages/s08_zoom_cloud/terraform/example.tfvars stages/s08_zoom_cloud/terraform/terraform.tfvars
# Edit project_id, region, github_repo, etc.

# 2. Provision the cluster + bucket + Artifact Registry + WIF
cd stages/s08_zoom_cloud/terraform
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars   # ~10 min for first apply

# 3. Capture outputs into GitHub secrets and shell env
terraform output                              # check what's there
gcloud container clusters get-credentials mandelflow --region <region>

# 4. Build and push the image
docker buildx build --platform linux/amd64 \
  -t <region>-docker.pkg.dev/<project>/mandelflow/compute:dev .
docker push <region>-docker.pkg.dev/<project>/mandelflow/compute:dev

# 5. (Future) launch the Dagster job that materialises the iterations asset
#    against the K8s executor. For now, submit individual Pods manually
#    to validate the plumbing:
kubectl apply -f stages/s08_zoom_cloud/k8s/compute-pod.yaml

# 6. Verify chunks landed
gsutil ls gs://<bucket>/runs/<run_id>.zarr/iterations/

# 7. TEAR IT DOWN
cd stages/s08_zoom_cloud/terraform
terraform destroy -var-file=terraform.tfvars
```

## What lives in each subdirectory

```
stages/s08_zoom_cloud/
├── README.md          ← this file
├── compute.py         ← re-exports s06's compute_frame (same kernel)
├── run.py             ← driver sketch: build K8s Job per frame, await completion
├── terraform/         ← infra-as-code; one .tf per resource type
│   ├── main.tf
│   ├── variables.tf
│   ├── gke.tf
│   ├── gcs.tf
│   ├── artifact_registry.tf
│   ├── workload_identity.tf
│   ├── outputs.tf
│   └── example.tfvars
├── k8s/               ← Pod / Job manifests applied by `run.py` (or Dagster)
│   └── compute-pod.yaml
└── dev/               ← local plumbing tests against a `kind` cluster
    └── kind-cluster.yaml
```

## Two paths to actually running this

### Path A: Direct K8s Job submission (simpler — what `run.py` will sketch)

For each frame index `k`, the driver builds a Pod spec, submits via `kubernetes` Python client, polls for completion, returns. No Dagster needed. Sufficient to validate the cluster + image + GCS write path end-to-end. This is what the local `kind` plumbing test in `dev/` will exercise.

### Path B: Dagster K8s executor (the architectural target)

The `iterations` asset is partitioned by frame; Dagster's `k8s_job_executor` launches one Job per partition automatically. The asset graph in `orchestration/definitions.py` is unchanged from local Dagster runs — only the executor config and the IOManager change. Materialise via `dagster job execute` or the UI; chunks land in `gs://.../run.zarr` as Pods complete.

Path B is the real story but depends on `orchestration/definitions.py` existing and on the **`GCSIcechunkIOManager`** (called out as a known gap in `docs/DESIGN.md §11`). Falls back to raw Zarr region writes if icechunk integration proves heavier than expected.

## Known gaps before this stage runs

In rough order of effort:

1. **Project-level GCP setup.** Create the project, enable billing, enable the APIs Terraform will need (`container.googleapis.com`, `artifactregistry.googleapis.com`, `iam.googleapis.com`, `iamcredentials.googleapis.com`, `storage.googleapis.com`, `compute.googleapis.com`). This is a one-time ~10-min task.
2. **Quota for T4 GPUs.** Default quota is often 0 in new projects. File a quota increase: `Compute Engine API → NVIDIA T4 GPUs` → 1+ in your region. Approval is usually same-day.
3. **Fill in the Terraform variables.** `terraform/example.tfvars` has placeholders.
4. **Build the Docker image.** Repo-root `Dockerfile` is already there; needs to push to Artifact Registry.
5. **`orchestration/definitions.py`** for Path B (Dagster). Not blocking for Path A.
6. **`GCSIcechunkIOManager`** for the parallel-write path. Or fall back to raw Zarr (single-writer-per-chunk via region writes, which we already have).

The scaffolded files mark these with `# TODO(s08):` comments at the relevant spots.

## What scaffolded *now* gives you

A clear deployment roadmap and Terraform skeletons that already reflect the right shape:

- Service accounts and Workload Identity bindings sketched.
- GKE cluster + GPU node pool with the right machine type, taints, and tolerations.
- GCS bucket with the right lifecycle (Standard storage, soft delete enabled).
- Artifact Registry repository scoped to the project.

Running `terraform plan` against a real project (with your variables filled in) should give a clean plan — though `apply` will reject anything that uses placeholder names until you customise.

## Cost cautions (worth repeating)

- **Cloud Load Balancers persist if you don't delete them.** ~$18/month each. None of the manifests here create one — Cloud Run for the viewer (s09) avoids this — but be vigilant.
- **GPU nodes do not stop when idle.** They keep billing until the node pool is scaled to zero or deleted.
- **GCS standard storage** is cheap but lifecycle to nearline / coldline after 30 days if you're keeping runs around.
- **Always run `terraform destroy`** when you finish a session. Reapplying is cheap; an idle GPU pool overnight is not.
