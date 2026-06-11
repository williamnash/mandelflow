# mandelflow GKE shared infrastructure — Terraform root.
#
# This is the cloud foundation for any GKE-backed stage. s09 (CPU fan-out) is
# the first to need it; s11 (GPU fan-out) layers on top by setting
# `gpu_node_count > 0` here. There is intentionally no separate terraform
# directory for s11 — the GPU node pool is one resource toggled by a variable.
#
# Layering with s08:
#   s08's terraform owns the project-level resources (GCS bucket, Artifact
#   Registry, project APIs, billing budget). This stage assumes those exist
#   and references the bucket via a data source. Run s08's terraform first.
#
# Usage:
#   cp example.tfvars terraform.tfvars   # fill in your values
#   terraform init
#   terraform apply -var-file=terraform.tfvars
#
#   # To add GPUs (s11): bump gpu_node_count in terraform.tfvars and re-apply.

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  billing_project       = var.project_id
  user_project_override = true
}

# Idempotent: s08 already enables most of these. `container` + `iamcredentials`
# are the ones unique to this stage; declaring the full set keeps the file
# self-documenting and re-applies harmlessly.
resource "google_project_service" "required_apis" {
  for_each = toset([
    "container.googleapis.com",        # GKE
    "iamcredentials.googleapis.com",   # WIF token exchange
    "artifactregistry.googleapis.com", # pulled images
    "iam.googleapis.com",              # service accounts
    "storage.googleapis.com",          # bucket access
    "compute.googleapis.com",          # node pool VMs
  ])
  service            = each.value
  disable_on_destroy = false
}

# The bucket is owned by s08's terraform. Look it up by name so we can grant
# the compute SA write access without duplicating the resource definition.
data "google_storage_bucket" "zarr_outputs" {
  name = var.bucket_name
}
