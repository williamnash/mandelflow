# Docker image repository, shared with s09 if you do both stages.
# Module-level `for_each` would let us avoid the duplicate resource between
# s08 and s09 but at the cost of a more complex root module — for a
# scaffold, declaring it in each stage's terraform/ is fine. terraform apply
# is idempotent: if you've already created `mandelflow` in s09, importing it
# into s08's state is one `terraform import` command.

resource "google_artifact_registry_repository" "mandelflow" {
  location      = var.region
  repository_id = "mandelflow"
  description   = "Container images for mandelflow stages 06, 08, 09"
  format        = "DOCKER"

  depends_on = [
    google_project_service.required_apis,
  ]
}
