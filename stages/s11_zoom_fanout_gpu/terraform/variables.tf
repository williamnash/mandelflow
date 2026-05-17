variable "project_id" {
  description = "GCP project ID. Project must exist with billing enabled."
  type        = string
}

variable "region" {
  description = "GCP region for all regional resources (cluster, bucket, AR)."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zone for the GPU node pool (must be in `region` and have T4 quota)."
  type        = string
  default     = "us-central1-a"
}

variable "cluster_name" {
  description = "GKE cluster name."
  type        = string
  default     = "mandelflow"
}

variable "github_owner" {
  description = "GitHub username or org that hosts the repo (for the WIF binding)."
  type        = string
}

variable "github_repo" {
  description = "GitHub repo name, e.g. `mandelflow`."
  type        = string
}

variable "gpu_machine_type" {
  description = "Machine type for the GPU node pool. n1-standard-4 + T4 is the minimum that fits."
  type        = string
  default     = "n1-standard-4"
}

variable "gpu_node_count" {
  description = "Number of GPU nodes. 1 is fine for demo; scale up only for real fan-out."
  type        = number
  default     = 1
}

variable "bucket_name" {
  description = "GCS bucket for Zarr outputs. Must be globally unique."
  type        = string
}
