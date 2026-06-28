resource "google_artifact_registry_repository" "docker" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repository
  format        = "DOCKER"
  description   = "Container images for toddler-private-rag (backend / frontend)."

  depends_on = [google_project_service.services]
}
