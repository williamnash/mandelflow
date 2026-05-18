# Runbook — bring mandelflow's cloud CPU fan-out (s09 GKE) up from scratch

This is the playbook for setting up the cloud fan-out path from a fresh
laptop and a fresh GCP project. Real wall-clock timings, real failure
modes, real fixes — captured as we did them on 2026-05-18. If a section
ends with "(fix below)", the failure happened and the fix lives further
down; don't paper over it on the next setup, do it right the first time.

Companion docs:

  - `CLOUD_SETUP.md` — the s08 (single VM) cloud foundation; this runbook
    layers on top of a project that already has s08's terraform applied.
  - `FANOUT.md` — *why* this architecture is shaped the way it is.
  - `GOTCHAS.md` — sharp edges to grep before debugging.

## 0. Prerequisites you should have before starting

- A GCP project with billing enabled.
- s08's terraform applied (provides the GCS bucket, AR repo, project APIs).
  See `CLOUD_SETUP.md` if you haven't.
- macOS, Linux, or WSL2. (Tested on macOS 15 / Apple Silicon.)
- `gcloud` CLI installed (brew cask `google-cloud-sdk` works fine).
- `uv` for Python deps.
- ADC auth: `gcloud auth login && gcloud auth application-default login`.

## 1. Install kubectl + gke-gcloud-auth-plugin

GKE clusters since K8s 1.26 require `gke-gcloud-auth-plugin` for `kubectl`
authentication. On brew-managed gcloud the kubectl binary isn't symlinked
to `/opt/homebrew/bin/`, so we need a PATH addition.

```bash
gcloud components install kubectl gke-gcloud-auth-plugin --quiet
```

Both binaries land in `/opt/homebrew/share/google-cloud-sdk/bin/` on brew
installs. Add to PATH (one-line ~/.zshrc append):

```bash
echo 'export PATH="/opt/homebrew/share/google-cloud-sdk/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Verify:

```bash
kubectl version --client
gke-gcloud-auth-plugin --version
```

## 2. Audit baseline — what's already in the project

Before bringing up new infra, capture what's there. `scripts/audit_cloud.sh`
walks every GCP resource type that could be billing and groups them by
cost model (always-billing vs free-idle).

```bash
scripts/audit_cloud.sh
```

Expected baseline after s08 applied, nothing else: 1 stopped VM
(`mandelflow-vm`), 1 disk (50 GB), 2 GCS buckets, 1 AR repo. No GKE
cluster, no LB, no static IPs. **Always-billing cost ~$2/month** (just
the stopped VM's disk).

If anything else shows up — a forgotten Cloud Run service, an orphan disk
— deal with it before bringing up the cluster.

## 3. Fill in terraform.tfvars

```bash
cd stages/s09_zoom_fanout_cpu/terraform
cp example.tfvars terraform.tfvars
```

Edit `terraform.tfvars` to match your project. The values used on
2026-05-18:

```hcl
project_id   = "mandelflow-2026"
region       = "us-central1"
zone         = "us-central1-b"     # us-central1-a hit resource exhaustion last time
cluster_name = "mandelflow"

github_owner = "williamnash"        # for WIF binding scope; OK to leave as
github_repo  = "mandelflow"         # placeholder if not using CI yet

bucket_name = "mandelflow-2026-zarr"  # MUST match s08's terraform.tfvars

cpu_min_nodes = 1
cpu_max_nodes = 8                    # >= MANDELFLOW_N_PODS for largest planned workload

gpu_node_count   = 0                 # set to 1 later for s11
gpu_machine_type = "n1-standard-4"
```

This file is `.gitignore`d. Never commit it.

## 4. terraform apply

```bash
terraform init    # first time only
terraform plan -var-file=terraform.tfvars  # read-only preview
terraform apply -var-file=terraform.tfvars -auto-approve
```

**Expected:** 17 resources to add. Wall-clock ~10 min, almost entirely on
the cluster control plane (6–10 min).

**Cost meter starts here:** ~$0.10/hr cluster control plane + ~$0.07/hr per
running node (starts with 1).

### Known failure mode: WIF pool propagation race

On the first apply, one resource sometimes fails with:

```
Error 400: Identity Pool does not exist (<project>.svc.id.goog).
Please check that you specified a valid resource name…
```

This is `google_service_account_iam_member.compute_workload_identity` —
it tries to bind to the cluster's Workload Identity pool, but GCP IAM
doesn't see the pool yet (eventual consistency). Wait ~30 s, re-run:

```bash
terraform apply -var-file=terraform.tfvars -auto-approve
```

The second apply detects only the missing binding (1 to add) and lands
it in ~6 s.

After this, capture the outputs you'll need next:

```bash
terraform output -raw compute_service_account
# → mandelflow-compute@mandelflow-2026.iam.gserviceaccount.com
```

## 5. kubectl context + KSA + Workload Identity binding (K8s side)

Three commands:

```bash
# 5a. Fetch credentials → ~/.kube/config
gcloud container clusters get-credentials mandelflow --region us-central1

# 5b. Create the K8s ServiceAccount in default namespace
kubectl create serviceaccount compute-sa

# 5c. Annotate the KSA so it impersonates the GCP compute SA
kubectl annotate serviceaccount compute-sa \
  iam.gke.io/gcp-service-account=$(terraform output -raw compute_service_account)
```

**The annotation is the K8s half of the Workload Identity binding.** The
terraform created the GCP half (`google_service_account_iam_member`).
Both halves must agree. Verify:

```bash
kubectl get serviceaccount compute-sa -o yaml
# Should show iam.gke.io/gcp-service-account: mandelflow-compute@...
```

After this, any Pod using `serviceAccountName: compute-sa` can read/write
the Zarr bucket with no JSON keys — token exchange via the GKE metadata
server is automatic.

## 6. Build and push the image

```bash
cd ../../..  # back to repo root
gcloud builds submit --config cloudbuild.yaml --region us-central1 .
```

**Expected:** ~13 min for the first build (cold cache); ~90 s after that
thanks to the registry-backed BuildKit cache.

Cloud Build runs the multi-stage Dockerfile on an `E2_HIGHCPU_8` builder,
pushes `compute:dev` (the runtime tag) and `compute:cache` (BuildKit
cache layers) to Artifact Registry.

Image size as of 2026-05-18: **4.6 GB**. The CUDA + Mesa EGL runtime
base + the uv-resolved venv dominate. CPU-only Pods would in principle
not need CUDA — there's a future optimisation here (~3 GB slimmer image
would mean faster cold Pod starts).

### Verify the image landed

```bash
gcloud artifacts docker tags list \
  us-central1-docker.pkg.dev/<project>/mandelflow/compute --limit 5
# Should show `dev` and `cache` tags with recent CREATE_TIME.
```

## 7. First dispatch — the `portfolio` preset

Cheap-and-fast validation that everything wires up: small enough to be
~$0.05 of cluster time, big enough to exercise image pull on every node,
KSA→GSA token swap, multi-Pod parallel writes into one shared icechunk.

```bash
MANDELFLOW_PRESET=portfolio \
uv run python -m stages.s09_zoom_fanout_cpu.run \
  --target gke \
  --output gs://<bucket>/runs/portfolio-001.icechunk
```

The dispatcher (see `stages/s09_zoom_fanout_cpu/run.py`):
1. Resolves `RunConfig` from env — portfolio = 8 Pods × 75 frames × 1080² × 2048 iter
2. Pre-initialises the icechunk repo at the output URL (avoids the
   `Repository.open_or_create` race across Pods — GOTCHAS #17)
3. Renders the K8s Job YAML (template at
   `stages/s09_zoom_fanout_cpu/k8s/job.yaml.tmpl`)
4. `kubectl apply -f -` submits it
5. `kubectl wait --for=condition=complete` blocks until done
6. `kubectl logs job/...` streams the final combined log

In a separate terminal you can watch progress:

```bash
watch -n 2 'kubectl get pods; echo; kubectl get nodes'
```

### Known failure mode #1: zonal CPU quota exceeded

On the first attempt on 2026-05-18, the dispatch failed with:

```
FailedScaleUp: Node scale up in zones us-central1-a associated with
this pod failed: GCE quota exceeded.
```

Confusing because the *regional* CPU quota was 4096 / 8 used. The hit
quota is a **zonal** limit (often invisible in `gcloud compute regions
describe`). Default per-zone CPU in newer GCP projects is typically 24
vCPU; our cluster's regional node pool was trying to put 8 × e2-standard-2
(= 16 vCPU) but split across zones, hit a per-zone limit at 4 nodes
(8 vCPU per zone).

**Symptoms:**
- Cluster scales 1 → 4 nodes (the part that fits), then stalls.
- Pods 4–7 stay `Pending` with `FailedScaleUp` events.
- Eventually one of them fails outright.

**Compounding factor:** our Job template's `backoffLimit: 0` means *any*
Pod failure kills the whole Job, deleting the Pods that *were* working
mid-flight. Pod 0 had written ~20 frames before being killed.

**Fix (option A) — lower n_pods to fit current zonal capacity:**

```bash
MANDELFLOW_PRESET=portfolio MANDELFLOW_N_PODS=4 \
uv run python -m stages.s09_zoom_fanout_cpu.run --target gke --output ...
```

**Fix (option B) — raise backoffLimit** so a transient FailedScaleUp
doesn't take the working Pods with it. Edit
`stages/s09_zoom_fanout_cpu/k8s/job.yaml.tmpl`:

```diff
- backoffLimit: 0
+ backoffLimit: 2
```

**Fix (option C) — request a quota increase.** GCP Console → IAM & Admin
→ Quotas → "CPUs (region us-central1)" or per-zone CPU. Submit a request
for, say, 32 vCPU per zone. Approval is usually <24 h.

Apply A+B for tonight; pursue C for long-term headroom.

### Known failure mode #2: icechunk ConflictError on concurrent commit

Second dispatch attempt (same run, with `N_PODS=4` override) failed
differently:

```
icechunk.ConflictError: Failed to commit,
  expected parent: Some("44DP9GYZ1X6ESBS5ZM40"),
  actual parent: Some("WGY166BE5JMW5QWBN1PG")
```

Two Pods (0, 2) committed successfully. Pod 1 opened its writable session
when `main` was at `44DP…`. While Pod 1 was computing, Pod 2 finished and
committed `WGY1…`, advancing `main`. Pod 1's eventual `commit()` failed
because the parent it expected (`44DP…`) was no longer the tip.

This is icechunk's optimistic-concurrency contract: each session commits
on the parent it observed at session open, and a conflict is raised if
that parent has moved. With our `backoffLimit: 0`, the Pod failure killed
the whole Job.

**Fix:** wrap `session.commit()` in a rebase-on-conflict loop. Disjoint
region writes (each Pod owns a distinct frame range = distinct chunks)
are mergeable by `BasicConflictSolver`, so the rebase trivially succeeds
and a retry commit lands on the new tip.

The pattern, now in `stages/s09_zoom_fanout_cpu/run.py`:

```python
import icechunk

for attempt in range(10):
    try:
        snapshot = session.commit(message)
        break
    except icechunk.ConflictError:
        if attempt == 9:
            raise
        session.rebase(icechunk.BasicConflictSolver())
```

This pattern is generic — it's how *any* multi-writer icechunk workload
handles concurrent commits. Capture it in your project from the start.
Documented in `GOTCHAS.md` #17 (parent-of-this-runbook).

## 8. Tear down

```bash
scripts/destroy_all.sh
# Interactive. Destroys s09 GKE state first (cluster + node pool + WIF),
# then s08 foundation (VM + bucket + AR). Each prompts y/N.
```

`scripts/destroy_all.sh --yes` to skip prompts. Calls
`scripts/audit_cloud.sh` at the end so you see anything that lingered.

## 9. Cost ledger (what each step costs)

| Step | One-shot cost | Recurring while up |
|---|---|---|
| terraform apply | $0 | ~$0.17/hr cluster + 1 node |
| Cloud Build (first) | ~$0.05 | $0 (one-shot) |
| Cloud Build (cache-warm) | ~$0.01 | $0 |
| portfolio dispatch | ~$0.05 (4–5 min × 8 nodes scaled up) | $0 |
| showcase dispatch | ~$0.30 (20 min × 8 nodes scaled up) | $0 |
| **Daily idle if not destroyed** | — | **~$4/day** |

The cluster control plane is the largest "leak if you forget" risk —
$0.10/hr × 24 = $2.40/day, and unlike VMs it doesn't have a "stop"
option, only destroy.

## Appendix — relevant gotchas to grep first

If something breaks during this runbook, consult `docs/GOTCHAS.md`:

- **#7** GKE Standard, not Autopilot
- **#11** icechunk session lifecycle / commit
- **#15** Pod-per-frame is the wrong fan-out shape
- **#16** dagster CLI --partition-range needs single_run or daemon
- **#17** icechunk Repository.open_or_create not race-safe
- **#18** Cluster node-pool size must match n_pods
