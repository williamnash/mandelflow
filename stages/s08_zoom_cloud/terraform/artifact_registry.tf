# Docker image repository for the mandelflow compute image.
# Pods pull from `<region>-docker.pkg.dev/<project>/mandelflow/<image>:<tag>`.

resource "google_artifact_registry_repository" "mandelflow" {
  location      = var.region
  repository_id = "mandelflow"
  description   = "Container images for mandelflow stages 06, 08, 09"
  format        = "DOCKER"

  depends_on = [
    google_project_service.required_apis,
  ]
}
