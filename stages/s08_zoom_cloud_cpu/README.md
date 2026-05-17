# Stage 08 — Single cloud machine, CPU kernel

The simplest cloud-deployment shape: one **GCE VM** running mandelflow's existing Docker image with the **s03 numba kernel**, output written to GCS. No cluster, no Kubernetes, no GPU. This is the first stage in the cloud progression and the deployable target while GPU quota is unresolved.

## Where this sits in the cloud progression

|  | CPU | GPU |
|---|---|---|
| Single | **s08** (this stage) | [s10](../s10_zoom_cloud_gpu/) — placeholder |
| Many | [s09](../s09_zoom_fanout_cpu/) — placeholder | [s11](../s11_zoom_fanout_gpu/) — scaffold |

Each adjacent stage adds exactly one axis: **s09** = s08 + machine count; **s10** = s08 + GPU; **s11** = both.

## Why a VM (and not GKE / Cloud Run / Vertex)

| Option | What it adds | Why we skip at s08 |
|---|---|---|
| **GCE VM** ✓ | "Rent a computer." | The simplest primitive. Same mental model as EC2 + a generic VM. |
| GKE | Orchestrated containers, multi-Pod fan-out. | Cluster overhead isn't justified for one machine — that's s11. |
| Cloud Run Jobs | Serverless containers. | Newer feature, regional constraints; the multi-CPU fan-out version (s09) is the natural place for Cloud Run Jobs. |
| Vertex AI Custom Job | Purpose-built ML batch. | Pulls in Vertex SDK + opinionated job spec; same teaching outcome as a VM at our scale. |

The VM is *also* the cheapest thing to teach because the lifecycle is obvious: `terraform apply` → SSH in → render finishes → `terraform destroy`. No cluster control plane charges between apply and destroy.

## What gets provisioned

| Resource | Purpose | Approx. cost |
|---|---|---|
| `e2-standard-2` GCE VM (2 vCPU, 8 GB) | Runs the mandelflow container, s03 CPU kernel | ~$0.067/hr while running |
| Container-Optimized OS boot disk | Smaller + Docker preinstalled, no apt detour | included |
| **GCS bucket** | Holds `runs/<id>.zarr` | pennies (under 5 GB free tier) |
| **Service account** + IAM bindings | VM → GCS access (no JSON keys) | free |
| **Artifact Registry** | Hosts the Docker image | pennies (~$0.20/month for the ~2 GB image) |
| **IAP-only SSH firewall rule** | Restricts port 22 to Identity-Aware Proxy | free |
| **$50 budget with $10/$50 alerts** | Email on threshold spend | free |

A 5-minute render → tear-down cycle costs **about $0.01**. Forgetting to tear down for a weekend costs ~$3–4. The budget alert catches anything beyond.

## Credentials, in order

You only need two of the three credential paths s11 needs — VMs avoid the Workload-Identity-binding dance because they carry a service account directly.

### 1. Local Terraform / `gcloud` (you, on your laptop)

```bash
gcloud auth login
gcloud auth application-default login   # for Terraform
gcloud config set project YOUR_PROJECT_ID
```

ADC reads from `~/.config/gcloud/application_default_credentials.json`. No JSON keys to manage.

### 2. The VM → GCS (attached service account)

Terraform creates a GCP service account `mandelflow-vm@<project>.iam.gserviceaccount.com` with `roles/storage.objectAdmin` on the Zarr bucket, and **attaches it directly to the VM**. Anything running on the VM (your container, an SSH session) inherits that identity via the **metadata server** — no JSON keys, no Workload Identity binding, no token exchange.

The COS image is hardened: no public IP, SSH only via IAP tunnel, narrow OAuth scopes (`storage-rw`, `logging-write`, `cloud-platform.read-only`), and the docker credential helper preinstalled for Artifact Registry pulls.

## Deployment flow

```bash
# 1. Fill tfvars
cp stages/s08_zoom_cloud_cpu/terraform/example.tfvars \
   stages/s08_zoom_cloud_cpu/terraform/terraform.tfvars
# edit project_id, region, zone, bucket_name, billing_account

# 2. Provision (~2 min)
cd stages/s08_zoom_cloud_cpu/terraform
terraform init
terraform apply -var-file=terraform.tfvars

# 3. Build + push the image via Cloud Build (no local Docker)
cd ../../..
gcloud builds submit --config cloudbuild.yaml --region us-central1 .

# 4. SSH onto the VM via IAP and run the container
gcloud compute ssh mandelflow-vm --zone=<zone> --tunnel-through-iap
# On the VM:
docker run \
  -e PYTHONUNBUFFERED=1 \
  us-central1-docker.pkg.dev/<project>/mandelflow/compute:dev \
  python -m stages.s08_zoom_cloud_cpu.run \
    --n-frames 60 --resolution 480 --max-iter 256 \
    --output gs://<bucket>/runs/dev.zarr

# 5. Pull results back to your laptop
gsutil -m cp -r gs://<bucket>/runs/dev.zarr ./out/

# 6. TEAR IT DOWN
gcloud artifacts docker images delete \
  us-central1-docker.pkg.dev/<project>/mandelflow/compute:dev --delete-tags
terraform destroy -var-file=terraform.tfvars
```

The bucket has `force_destroy = true` so any Zarrs inside are removed when the bucket is destroyed.

## How `run.py` differs from s07

It's barely different. s07's loop, with:

- `--output` can be a `gs://bucket/path.zarr` URL — xarray + zarr + gcsfs speak GCS through the existing `common.store.write_frame` API.
- No GL context is acquired — the compute kernel imported from `stages.s08_zoom_cloud_cpu.compute` is **s03** (numba, single-thread + fastmath + early exits), not s06 (GPU shader). That's the swap that distinguishes a CPU deploy from a GPU one.

For the standalone CLI, `--output gs://bucket/path.zarr` is the only deployment-aware change.

## When to graduate to s09 / s10 / s11

- **s09** (multi-CPU fan-out): when a single CPU VM's wall-clock is the bottleneck. Cloud Run Jobs is the natural shape.
- **s10** (single GPU VM): when you have GPU quota or want to demo the GPU kernel against a real cloud GPU.
- **s11** (multi-GPU GKE): the production pattern. Both axes combined.

## Expected perf

s03 at 1080² on an e2-standard-2 vCPU should be roughly **0.5–1 s/frame** (vs ~12 ms/frame for s06 on a T4). For a 120-frame demo zoom: **~1–2 minutes** wall-clock. Cost: pennies.

That's the right scale for "validate the cloud pipeline end-to-end" — long enough to see the timing, short enough to not melt your budget.
