# Stage 08 — Cloud, single machine

**Status: scaffold only.** Terraform skeleton + walkthrough; not provisioned, not pushed.

s08 is the smallest possible "run mandelflow in the cloud" deployment: one **GCE VM** with a T4 GPU, the project's existing Docker image running on it, output written to GCS. It teaches the credentials story, the container delivery path, and the GCS write semantics — without inheriting the operational weight of a Kubernetes cluster.

If you've never deployed to a cloud GPU before, this is the right stage to start with. **s09** picks up the same pattern and fans frame ranges across multiple machines once single-machine throughput stops being enough.

## Why a VM (and not GKE / Cloud Run / Vertex)

| Option | What it adds | Why we skip at s08 |
|---|---|---|
| **GCE VM** ✓ | "Rent a computer with a GPU." | The simplest primitive. Same mental model as EC2 + GPU. |
| GKE | Orchestrated containers, multi-Pod fan-out, autoscaling. | Cluster overhead isn't justified for one machine — that's s09. |
| Cloud Run GPU | Serverless containers. | Newer feature, regional constraints; black-boxes the VM you'd otherwise see directly. |
| Vertex AI Custom Job | Purpose-built ML batch. | Pulls in Vertex SDK + opinionated job spec; same teaching outcome as a VM at our scale. |

The VM is *also* the cheapest thing to teach because the lifecycle is obvious: `terraform apply` → SSH in (or wait for the startup script) → render finishes → `terraform destroy`. No cluster control plane charges between apply and destroy.

## What gets provisioned

| Resource | Purpose | Approx. cost |
|---|---|---|
| `n1-standard-4` GCE VM + **1× T4 GPU** | Runs the mandelflow container | ~$0.40/hr while running |
| **GCS bucket** | Holds `runs/<id>.zarr` | pennies |
| **Service account** + IAM bindings | VM → GCS access (no JSON keys) | free |
| **Artifact Registry** (shared if you also do s09) | Hosts the Docker image | pennies |

A 5-minute render → tear-down cycle costs **about $0.03**. Forgetting to tear down for a weekend costs ~$20. **Set a phone alarm before you stop watching the VM.**

## Credentials, in order

You only need two of the three credential paths s09 needs — VMs avoid the Workload-Identity-binding dance because they carry a service account directly.

### 1. Local Terraform / `gcloud` (you, on your laptop)

```bash
gcloud auth login
gcloud auth application-default login         # for Terraform
gcloud config set project YOUR_PROJECT_ID
```

ADC reads from `~/.config/gcloud/application_default_credentials.json`. No JSON keys to manage.

### 2. The VM → GCS (attached service account)

The Terraform creates a GCP service account `mandelflow-vm@<project>.iam.gserviceaccount.com` with `roles/storage.objectAdmin` on the Zarr bucket, and **attaches it directly to the VM**. Anything running on the VM (your container, an SSH session) automatically inherits that identity via the **metadata server** — no JSON keys, no Workload Identity binding, no token exchange. Just `gcloud auth list` on the VM and the right principal is already active.

> Your "Google API key" isn't what this needs. API keys authenticate client requests to public Google APIs (Maps, Gemini). For provisioning GCP infrastructure and running batch GPU work in it you use the two flows above — ADC for your laptop, attached SA for the VM. **Zero static credentials**, by design.

## Deployment flow

```bash
# 0. Prerequisites: GCP project with billing, T4 GPU quota in your region.

# 1. Fill in tfvars (project_id, region, zone, bucket_name)
cp stages/s08_zoom_cloud/terraform/example.tfvars stages/s08_zoom_cloud/terraform/terraform.tfvars
# edit the file

# 2. Provision the VM + bucket + SA bindings
cd stages/s08_zoom_cloud/terraform
terraform init
terraform apply -var-file=terraform.tfvars   # ~2 min

# 3. Build and push the Docker image to Artifact Registry
#    (image is shared with s09 if you've done it before)
docker buildx build --platform linux/amd64 \
  -t <region>-docker.pkg.dev/<project>/mandelflow/compute:dev .
docker push <region>-docker.pkg.dev/<project>/mandelflow/compute:dev

# 4. SSH onto the VM and run the container
gcloud compute ssh mandelflow-vm --zone=<zone>
# On the VM:
docker run --gpus all \
  -e PYTHONUNBUFFERED=1 \
  <region>-docker.pkg.dev/<project>/mandelflow/compute:dev \
  python -m stages.s08_zoom_cloud.run \
    --n-frames 120 --resolution 1080 --max-iter 512 \
    --output gs://<bucket>/runs/dev.zarr

# 5. Pull results back
gsutil -m cp -r gs://<bucket>/runs/dev.zarr ./

# 6. TEAR IT DOWN
terraform destroy -var-file=terraform.tfvars
```

The startup script the VM gets includes the NVIDIA driver install — first boot takes ~3–5 minutes for that step before Docker can see the GPU. The driver state survives reboot; subsequent runs are immediate.

## How `run.py` differs from s07

It barely differs. `run.py` is s07's exact loop — the canonical schedule, shared GL context across all frames, multi-frame Zarr writes — with **one change**: the output path can be a `gs://` URL. The xarray + zarr stack speaks GCS through `gcsfs` (already in `pyproject.toml` deps), so `xarray.to_zarr("gs://bucket/path.zarr", region=...)` works directly. No code change in `common/store.py` needed; the same `region` write API targets either filesystem.

For the standalone CLI, `--output gs://bucket/path.zarr` is the only deployment-aware change.

## What this stage doesn't (yet) do

- **MP4 stitching from the GCS Zarr.** `render/animation.py` reads via `xr.open_zarr` so it should work against `gs://` URLs too, but currently the local-development assumption is hard-coded. Small follow-up.
- **Fan-out across machines.** That's s09's job and it builds directly on this stage.
- **Cost telemetry.** The Terraform doesn't tag resources with cost-center labels. Add `labels = { stage = "s08", purpose = "mandelflow-demo" }` to the VM resource once you actually deploy.

## When to graduate to s09

Single-VM s08 is right when:
- Your render finishes in seconds-to-minutes on one T4.
- You're iterating on the kernel and want a tight cycle.
- Tearing down between runs is acceptable.

Graduate to s09 when:
- One T4's wall-clock becomes the bottleneck (e.g., 10k-frame zoom).
- You need independent retries per frame range.
- You want fan-out as the architectural lesson, not just throughput.
