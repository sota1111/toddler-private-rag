resource "google_storage_bucket" "attachments" {
  project                     = var.project_id
  name                        = var.gcs_bucket_name
  location                    = var.gcs_bucket_location
  uniform_bucket_level_access = true
  force_destroy               = false

  # Keep attachment history; objects are not auto-deleted. Reconcile against
  # docs/data-retention-policy.md if a lifecycle policy is desired later.

  depends_on = [google_project_service.services]
}
