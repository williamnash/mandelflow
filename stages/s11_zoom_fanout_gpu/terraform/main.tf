# mandelflow stage 11 — Terraform root.
#
# Provisions everything needed to fan frame computation across a GKE cluster
# and write per-frame chunks to GCS. See ../README.md for the deployment
# walkthrough.
#
# Usage:
#   cp example.tfvars terraform.tfvars   # fill in your values
#   terraform init
#   terraform apply -var-file=terraform.tfvars

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # TODO(s11): swap to a GCS-backed remote backend once the bucket below exists,
  # so state is shared between you and CI. For first apply, local backend is
  # fine; create the bucket, then move state via `terraform init -migrate-state`.
  # backend "gcs" {
  #   bucket = "<project-id>-tfstate"
  #   prefix = "stages/s11_zoom_fanout_gpu"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable the APIs the rest of this configuration needs. Cheap and idempotent.
resource "google_project_service" "required_apis" {
  for_each = toset([
    "container.googleapis.com",          # GKE
    "artifactregistry.googleapis.com",   # Docker image repo
    "iam.googleapis.com",                # service accounts
    "iamcredentials.googleapis.com",     # WIF token exchange
    "storage.googleapis.com",            # GCS bucket
    "compute.googleapis.com",            # node pool VMs
  ])
  service            = each.value
  disable_on_destroy = false
}
