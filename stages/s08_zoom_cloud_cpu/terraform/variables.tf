variable "project_id" {
  description = "GCP project ID. Project must exist with billing enabled."
  type        = string
}

variable "region" {
  description = "GCP region for the GCS bucket and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone for the VM (must be in `region` and have T4 quota)."
  type        = string
  default     = "us-central1-a"
}

variable "vm_name" {
  description = "Compute Engine instance name."
  type        = string
  default     = "mandelflow-vm"
}

variable "machine_type" {
  description = "Machine type. n1-standard-4 is the minimum that fits a T4."
  type        = string
  default     = "n1-standard-4"
}

variable "boot_disk_size_gb" {
  description = "Boot disk size in GB. Container images + NVIDIA drivers need ~30GB headroom."
  type        = number
  default     = 50
}

variable "bucket_name" {
  description = "GCS bucket for Zarr outputs. Must be globally unique."
  type        = string
}

variable "billing_account" {
  description = "GCP billing account ID for the budget resource (e.g. `01ABCD-EFGH12-IJKLMN`). Find via `gcloud billing accounts list`."
  type        = string
}
