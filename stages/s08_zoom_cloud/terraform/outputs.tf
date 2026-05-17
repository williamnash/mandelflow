output "vm_name" {
  value       = google_compute_instance.mandelflow_vm.name
  description = "SSH with: gcloud compute ssh <vm_name> --zone=<zone>"
}

output "vm_zone" {
  value       = google_compute_instance.mandelflow_vm.zone
  description = "Pass to `gcloud compute ssh --zone`."
}

output "vm_external_ip" {
  value       = google_compute_instance.mandelflow_vm.network_interface[0].access_config[0].nat_ip
  description = "Ephemeral public IP of the VM."
}

output "zarr_bucket" {
  value       = google_storage_bucket.zarr_outputs.url
  description = "Pass to `--output` as `gs://<bucket>/runs/<run_id>.zarr`."
}

output "artifact_registry_url" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.mandelflow.repository_id}"
  description = "Image push target. Example: <url>/compute:dev"
}

output "vm_service_account" {
  value       = google_service_account.vm.email
  description = "The identity the VM uses to access GCS / Artifact Registry."
}
