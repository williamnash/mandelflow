# GCS bucket for Zarr outputs. One bucket holds all run.zarr stores under
# `gs://<bucket>/runs/<run_id>.zarr/`.
#
# Standard storage class for hot reads (the viewer in s09 will hit this).
# Soft delete is on (7-day default) so a stray `gsutil rm` doesn't lose data.

resource "google_storage_bucket" "zarr_outputs" {
  name     = var.bucket_name
  location = var.region

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # 30-day lifecycle move to nearline once we're keeping older runs around.
  # TODO(s08): enable this when we have runs worth archiving.
  # lifecycle_rule {
  #   condition { age = 30 }
  #   action {
  #     type          = "SetStorageClass"
  #     storage_class = "NEARLINE"
  #   }
  # }

  versioning {
    enabled = false
  }

  depends_on = [
    google_project_service.required_apis,
  ]
}
