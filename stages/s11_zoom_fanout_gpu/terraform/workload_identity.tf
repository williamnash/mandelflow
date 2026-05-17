# Workload Identity Federation: GitHub Actions → GCP, no static keys.
# Also: the runtime SA the compute Pods impersonate via GKE Workload Identity.
#
# Two trust paths land here:
#
# 1) GitHub OIDC → WIF pool → impersonate `deploy_sa` (used by .github/workflows/deploy.yml)
# 2) GKE Pod's KSA → impersonate `compute_sa` (used at runtime in GPU Pods)
#
# Both swap short-lived OIDC tokens for GCP IAM tokens. There are no JSON keys
# anywhere in this configuration on purpose.

# ── Deploy SA (used by CI) ────────────────────────────────────────────────────

resource "google_service_account" "deploy" {
  account_id   = "mandelflow-deploy"
  display_name = "mandelflow CI deploy"
}

# Push to Artifact Registry.
resource "google_project_iam_member" "deploy_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# Apply manifests / launch Jobs in the cluster.
resource "google_project_iam_member" "deploy_gke_developer" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# ── Compute SA (used at runtime by GPU Pods) ──────────────────────────────────

resource "google_service_account" "compute" {
  account_id   = "mandelflow-compute"
  display_name = "mandelflow GPU compute Pod runtime"
}

resource "google_storage_bucket_iam_member" "compute_zarr_writer" {
  bucket = google_storage_bucket.zarr_outputs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.compute.email}"
}

# Bind the K8s ServiceAccount `compute-sa` in namespace `default` to the GCP SA.
# Pods that use that KSA inherit the GCP SA's permissions via Workload Identity.
resource "google_service_account_iam_member" "compute_workload_identity" {
  service_account_id = google_service_account.compute.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/compute-sa]"
}

# ── WIF pool + provider for GitHub OIDC ──────────────────────────────────────

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions WIF pool"
  depends_on = [
    google_project_service.required_apis,
  ]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.actor"      = "assertion.actor"
  }

  # Only trust pushes from this repo.
  attribute_condition = "assertion.repository == '${var.github_owner}/${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Let the WIF pool's principals (filtered by the attribute condition above)
# impersonate the deploy SA.
resource "google_service_account_iam_member" "github_can_impersonate_deploy" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}
