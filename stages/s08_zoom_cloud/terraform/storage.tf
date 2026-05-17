# GCS bucket for Zarr outputs and the service account the VM attaches to.
# The VM inherits the SA's identity at runtime via the metadata server —
# no JSON keys, no Workload Identity binding, no token exchange.

resource "google_storage_bucket" "zarr_outputs" {
  name     = var.bucket_name
  location = var.region

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = false
  }

  depends_on = [
    google_project_service.required_apis,
  ]
}

resource "google_service_account" "vm" {
  account_id   = "mandelflow-vm"
  display_name = "mandelflow s08 VM runtime"
}

resource "google_storage_bucket_iam_member" "vm_zarr_writer" {
  bucket = google_storage_bucket.zarr_outputs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.vm.email}"
}

# Read access to Artifact Registry so the VM can pull the mandelflow image.
resource "google_project_iam_member" "vm_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.vm.email}"
}
