# Cloud setup playbook + lessons learned

A working record of provisioning mandelflow's cloud stages (s08–s11) on GCP from a clean slate, plus the sharp edges hit along the way. Written after the first attempt on 2026-05-17, which deployed s08's infrastructure end-to-end and stopped at a Dockerfile fix.

This doc is two things:

1. **A repeatable setup playbook** for anyone (including future-you) deploying mandelflow's cloud stages.
2. **A gotchas journal** — every "wait, that's not how I thought it worked" moment, with the fix.

Cross-reference: [`docs/GOTCHAS.md`](GOTCHAS.md) covers code-side gotchas; this file is specifically about cloud provisioning and deployment.

---

## Setup playbook

### Phase 0 — Tooling

| | Install |
|---|---|
| `gcloud` | `brew install --cask google-cloud-sdk` (or download from cloud.google.com/sdk). Authenticate with `gcloud auth login` then `gcloud auth application-default login`. |
| `terraform` | **Not in the Homebrew core tap anymore** (license change). Use `brew tap hashicorp/tap && brew install hashicorp/tap/terraform`. |
| `docker` | **Skippable.** Cloud Build can build the image inside GCP without local Docker. Only install if you want to iterate the image locally. |

### Phase 1 — Project + billing + APIs

```bash
# Create a dedicated project (project IDs are globally unique)
gcloud projects create mandelflow-2026 --name="mandelflow"

# Link a billing account (find ID via: gcloud billing accounts list)
gcloud billing projects link mandelflow-2026 --billing-account=<your-billing-account-id>

# Set as active
gcloud config set project mandelflow-2026

# Enable bootstrap APIs (the rest are enabled by Terraform)
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  iamcredentials.googleapis.com \
  serviceusage.googleapis.com

# ADC for Terraform (browser OAuth flow)
gcloud auth application-default login

# Tell ADC which project to bill for API calls (some APIs need this; see Gotcha #1)
gcloud auth application-default set-quota-project mandelflow-2026
```

### Phase 2 — GPU quota request (if you want GPU stages)

For `s10_zoom_cloud_gpu` and `s11_zoom_fanout_gpu`:

1. Open <https://console.cloud.google.com/iam-admin/quotas?project=mandelflow-2026&service=compute.googleapis.com&metric=GPUS-ALL-REGIONS>
2. Tick the **"GPUs (all regions)"** row → Edit Quotas → request **1** (or 4 for `s11`).
3. New projects with no billing history are typically **denied with a 48-hour wait suggestion** — see Gotcha #2. The CPU stages don't need this.

### Phase 3 — Terraform

```bash
cp stages/s08_zoom_cloud_cpu/terraform/example.tfvars \
   stages/s08_zoom_cloud_cpu/terraform/terraform.tfvars
# Fill in: project_id, region, zone, bucket_name, billing_account

cd stages/s08_zoom_cloud_cpu/terraform
terraform init
terraform apply -var-file=terraform.tfvars   # ~2 min
```

### Phase 4 — Build the image via Cloud Build

```bash
cd <repo-root>
gcloud builds submit --config cloudbuild.yaml --region us-central1 .
# ~10–15 min for first build (CUDA layers pull from scratch).
```

### Phase 5 — Network prep (one-time, after VM creation)

```bash
# VMs without public IPs need Private Google Access to reach Google APIs.
gcloud compute networks subnets update default --region=us-central1 \
  --enable-private-ip-google-access
```

### Phase 6 — Run the container

```bash
gcloud compute ssh mandelflow-vm --zone=us-central1-b --tunnel-through-iap
# Inside the VM, authenticate Docker via the metadata server (see Gotcha #4):
TOKEN=$(curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "$TOKEN" | docker login -u oauth2accesstoken --password-stdin \
  https://us-central1-docker.pkg.dev

# Pull and run
docker pull us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev
docker run --rm -e PYTHONUNBUFFERED=1 \
  us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev \
  python -m stages.s08_zoom_cloud_cpu.run \
    --n-frames 30 --resolution 480 --max-iter 256 \
    --output gs://mandelflow-2026-zarr/runs/dev.zarr
```

### Phase 7 — Teardown (do this every time you finish)

```bash
# Stop the VM (preserves disk, halts compute billing)
gcloud compute instances stop mandelflow-vm --zone=us-central1-b

# OR: full destroy
gcloud artifacts docker images delete \
  us-central1-docker.pkg.dev/mandelflow-2026/mandelflow/compute:dev \
  --delete-tags
cd stages/s08_zoom_cloud_cpu/terraform
terraform destroy -var-file=terraform.tfvars
```

The bucket has `force_destroy = true` so terraform handles Zarr cleanup automatically. Artifact Registry has no `force_destroy` equivalent; clear the image first.

---

## Gotchas hit (and fixed)

### #1 — ADC quota project unset, billingbudgets API failure

**Symptom:**
```
Error 403: ... requires a quota project, which is not set by default.
```
`terraform apply` failed on `google_billing_budget` even though the API was enabled.

**Cause:** Some Google APIs (billingbudgets, others) bill API calls against a "quota project" rather than the resource project. ADC defaults to the SDK's internal project for user creds; the billingbudgets API doesn't accept that.

**Fix (two parts):**
1. `gcloud auth application-default set-quota-project mandelflow-2026`
2. In `terraform/main.tf`, add to the provider block:
   ```hcl
   provider "google" {
     project               = var.project_id
     region                = var.region
     billing_project       = var.project_id   # ← these two
     user_project_override = true             # ←
   }
   ```
   Without these, the provider doesn't pass the quota project header to the API.

### #2 — GPU quota denied on new projects

**Symptom:** Quota request for `GPUS_ALL_REGIONS` denied immediately with:
> "We are unable to grant you additional quota at this time. If this is a new project please wait 48h until you resubmit the request or until your Billing account has additional history."

**Cause:** GCP's fraud-prevention policy: new projects with billing accounts that have no usage history can't get GPU quota right away.

**Workarounds (in order of "least pain"):**
1. **Wait 48 hours** and resubmit. The infrastructure already provisioned costs $0 idle.
2. **Resubmit from an older project** that has billing history. Mixes projects but unblocks faster.
3. **Multi-cloud the GPU work** — AWS (`g4dn.xlarge` with T4) and Azure (NC-series) don't have this restriction.
4. **Cloud Run Jobs GPU** (L4) — newer feature, may have separate quota.

`stages/s10_zoom_cloud_gpu/README.md` and `stages/s11_zoom_fanout_gpu/README.md` cover the GPU stages; they remain placeholders until quota is granted.

### #3 — Cloud Build needs BuildKit explicitly enabled

**Symptom:** `gcloud builds submit --tag ...` fails partway through:
```
the --mount option requires BuildKit.
ERROR: build step 0 "gcr.io/cloud-builders/gcb-internal" failed
```
Our Dockerfile uses BuildKit syntax (`# syntax=docker/dockerfile:1.7` + `--mount=type=cache`).

**Cause:** Cloud Build's default builder doesn't enable BuildKit; the `--tag` shorthand uses it directly.

**Fix:** Use `cloudbuild.yaml` with `DOCKER_BUILDKIT=1`:
```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    env: ['DOCKER_BUILDKIT=1']
    args: ['build', '-t', 'us-central1-docker.pkg.dev/$PROJECT_ID/mandelflow/compute:dev', '.']
images: ['us-central1-docker.pkg.dev/$PROJECT_ID/mandelflow/compute:dev']
timeout: '1800s'
```
Then `gcloud builds submit --config cloudbuild.yaml`. See `cloudbuild.yaml` at the repo root.

### #4 — VM with no public IP can't reach `*.docker.pkg.dev` without Private Google Access

**Symptom:** `docker pull` from the VM times out:
```
Get "https://us-central1-docker.pkg.dev/v2/": net/http: request canceled while awaiting headers
```

**Cause:** The security-hardened VM has no `access_config` (no public IP), which by default also means no internet access. Even Google's own services aren't reachable from the VM without **Private Google Access** enabled on the subnet.

**Fix:**
```bash
gcloud compute networks subnets update default --region=us-central1 \
  --enable-private-ip-google-access
```
This is a one-time setting on the subnet. Could be added to Terraform; currently it's run manually as part of Phase 5. PGA covers `*.googleapis.com`, `*.docker.pkg.dev`, and other Google service domains.

**Alternative:** Cloud NAT, which gives outbound internet access to private VMs. More expensive (~$0.045/hr per gateway), but lets the VM reach anything. Overkill for our case.

### #5 — COS `/root/` is read-only; metadata startup scripts that touch `/root/.docker/` fail

**Symptom:** Startup script log on the VM shows:
```
ERROR: Unable to save docker config: mkdir /root/.docker: read-only file system
```
Subsequent `docker pull` fails with "Unauthenticated request" because the credential helper config never got written.

**Cause:** Container-Optimized OS is hardened — `/root/`, `/usr/`, and other system paths are read-only. The startup script runs as root, and `docker-credential-gcr` tries to write `/root/.docker/config.json`. There's no writable `~/.docker` for root on COS.

**Fix (one-time, on each VM after creation):** Authenticate Docker as the SSH user (whose `/home/<user>/` *is* writable), pulling a token from the metadata server:

```bash
TOKEN=$(curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "$TOKEN" | docker login -u oauth2accesstoken --password-stdin \
  https://us-central1-docker.pkg.dev
```
The token comes from the VM's attached service account, no JSON keys involved. Config lands at `~/.docker/config.json` and persists across `docker run` invocations as the same user.

**Cleaner fix (to do):** drop the broken startup script and use `gcr-credential-helper` which is preinstalled on COS for `*.gcr.io` — extending it to `*.pkg.dev` should be possible with a tweak. Or switch from COS to a CPU-Optimized Ubuntu image and run the startup script as the eventual user.

### #6 — Dockerfile venv `python` symlink points to a non-existent path in the runtime image

**Symptom:**
```
exec: "python": executable file not found in $PATH
```
And when forcing the full path:
```
exec: "/app/.venv/bin/python": stat ...: no such file or directory
```

**Cause:** uv builds the venv with the *builder image's* Python. The venv stores symlinks like `/app/.venv/bin/python → /usr/local/bin/python3`. The runtime image (`nvidia/cuda:...`) has Python installed via apt at `/usr/bin/python3.12`, *not* `/usr/local/bin/python3`. The symlink resolves to a path that doesn't exist in the runtime, so the binary is unreachable.

**Fix (applied):** option 1 — add a compatibility symlink in the runtime stage of the Dockerfile:

```dockerfile
RUN ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3
```

Other options considered: rebuild the venv inside the runtime stage (slower build, smaller image), install `uv` in the runtime, or use `uv run python` everywhere. Symlink is the smallest change and works for both `python` and `python3.12` venv shims.

### #7 — `default-allow-ssh` firewall rule auto-created on every project, must be deleted manually

**Symptom:** With our IAP-only firewall rule in place, the default `default-allow-ssh` rule (auto-created when the Compute API is enabled) is still allowing SSH from `0.0.0.0/0`. Multiple ALLOW rules combine permissively — you can't override an open ALLOW with a stricter ALLOW.

**Fix (one-time):**
```bash
gcloud compute firewall-rules delete default-allow-ssh --quiet
```
The Terraform doesn't manage this rule since it pre-exists. The IAP-only rule in `firewall.tf` becomes the only ingress rule for port 22.

### #8 — Terraform state lives with the directory; renames must carry it

**Symptom:** Renaming `stages/s08_zoom_cloud/` → `stages/s08_zoom_cloud_cpu/` mid-deployment. State files (`.tfstate`, `.terraform/`) live inside `terraform/`. When you `mv` the directory, state moves with it — terraform sees the existing state and the next `apply` only does deltas. **No `terraform import` needed.**

This worked cleanly. The other half: if you split a stage's resources across two directories, you DO need imports. We didn't need that here.

---

## What still needs doing

Captured as TODO items, not blockers for the 2026-05-17 progress:

- [x] **Fix the Dockerfile python symlink** (Gotcha #6). Done — `RUN ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3` in the runtime stage.
- [ ] **Move PGA to Terraform** (Gotcha #4). Add `google_compute_subnetwork` data + an `--enable-private-ip-google-access` flag, or skip and document the manual step.
- [ ] **Delete `default-allow-ssh` in Terraform** (Gotcha #7). Currently a manual `gcloud` command.
- [ ] **Bake `docker login` into the VM's startup OR a wrapper script** (Gotcha #5). So users don't have to do it manually after SSH.
- [ ] **State backend → GCS** so CI and laptop share state. The `main.tf` has a commented-out `backend "gcs"` block ready to enable.
- [ ] **Resubmit GPU quota after 2026-05-19** (48h post-denial).

---

## What was learned about the project layout

The 2×2 cloud progression that emerged after the GPU quota denial:

|        | CPU                          | GPU                              |
| ------ | ---------------------------- | -------------------------------- |
| Single | `s08_zoom_cloud_cpu` (done)  | `s10_zoom_cloud_gpu` (placeholder) |
| Many   | `s09_zoom_fanout_cpu` (placeholder) | `s11_zoom_fanout_gpu` (scaffold) |

Each adjacent stage adds exactly one axis. s08 is deployable today; s09/s10 are placeholders (deferred); s11 is scaffolded but blocked on GPU quota.

This shape replaced the earlier "s08 = cloud VM (GPU-aspirational)" framing once the quota denial forced explicit CPU vs GPU separation. **The lesson:** name the deployment-shape axis explicitly in stage IDs, not implicitly via README context.

---

## Current state of `mandelflow-2026`

As of 2026-05-17:

| Resource | State |
|---|---|
| Project `mandelflow-2026` | created, billing linked |
| ADC quota project | set |
| APIs enabled | compute, iam, storage, artifactregistry, cloudbuild, billingbudgets, iap, cloudresourcemanager, iamcredentials, serviceusage |
| Terraform state | local, at `stages/s08_zoom_cloud_cpu/terraform/.tfstate` |
| VM `mandelflow-vm` | provisioned in `us-central1-b`, may be running or stopped |
| GCS bucket `mandelflow-2026-zarr` | created, empty |
| Artifact Registry `mandelflow` | exists, holds `compute:dev` image |
| Workload Identity SA `mandelflow-vm` | provisioned with `roles/storage.objectAdmin` and `roles/artifactregistry.reader` |
| Firewall `allow-iap-ssh` | active, SSH only from IAP range |
| `default-allow-ssh` | deleted |
| Budget alert | $50 cap with $10/$50 thresholds |
| GPU quota | denied 2026-05-17, can resubmit 2026-05-19 |
| Image runnable | YES — Dockerfile python symlink applied, rebuild + push pushed `compute:dev@sha256:13580…` |
| Code executed end-to-end on the VM | **YES (2026-05-17)** — `docker run … python -m stages.s08_zoom_cloud_cpu.run` produced a 30-frame Zarr at `gs://mandelflow-2026-zarr/runs/first-run.zarr` (1.9 MB). Pulled locally; rendered to PNG + MP4 via existing pipeline. Full loop validated. |
| Compute kernel inside the container | **s04 (s03 numba kernel + Dask LocalCluster)** — single-thread on s03 was the original cloud build; we swapped to s04 so all VM cores are used. Same code on laptop saturates ~5 of 12 CPUs via Dask. |
| Cloud Build cache | configured: `:cache` tag in Artifact Registry; subsequent builds ~1-2 min instead of ~11 |
| VM | stopped (2026-05-17) — restart with `gcloud compute instances start mandelflow-vm --zone=us-central1-b` |

To pick up from here on a future session: read this doc top-to-bottom; the playbook order is the order the steps should run.
