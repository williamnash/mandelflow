# mandelflow stage 08 — Terraform root.
#
# Provisions one GCE VM with a T4 GPU, a GCS bucket for outputs, and the
# service account / IAM bindings that let the VM write to the bucket via
# its attached identity (no JSON keys). See ../README.md for the full
# deployment walkthrough.
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
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# Enable the APIs the rest of this configuration needs. Idempotent.
resource "google_project_service" "required_apis" {
  for_each = toset([
    "compute.googleapis.com",            # GCE VM
    "iam.googleapis.com",                # service accounts
    "storage.googleapis.com",            # GCS bucket
    "artifactregistry.googleapis.com",   # Docker image repo (shared with s09)
  ])
  service            = each.value
  disable_on_destroy = false
}
