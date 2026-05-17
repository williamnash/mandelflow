output "cluster_name" {
  value       = google_container_cluster.mandelflow.name
  description = "Pass to `gcloud container clusters get-credentials` after apply."
}

output "cluster_location" {
  value       = google_container_cluster.mandelflow.location
  description = "Region/zone the cluster was provisioned in."
}

output "artifact_registry_url" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.mandelflow.repository_id}"
  description = "Prefix for image tags. Example: <url>/compute:dev"
}

output "zarr_bucket" {
  value       = google_storage_bucket.zarr_outputs.url
  description = "GCS bucket holding run.zarr stores."
}

output "deploy_service_account" {
  value       = google_service_account.deploy.email
  description = "Set as the GCP_DEPLOY_SA GitHub secret."
}

output "workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Set as the GCP_WORKLOAD_IDENTITY_PROVIDER GitHub secret."
}

output "compute_service_account" {
  value       = google_service_account.compute.email
  description = "Annotate the `compute-sa` KSA with this so Pods get GCS access."
}
