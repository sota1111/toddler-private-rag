resource "google_storage_bucket" "attachments" {
  project                     = var.project_id
  name                        = var.gcs_bucket_name
  location                    = var.gcs_bucket_location
  uniform_bucket_level_access = true
  force_destroy               = false

  # Keep attachment history; objects are not auto-deleted. Reconcile against
  # docs/data-retention-policy.md if a lifecycle policy is desired later.

  # SOT-1377: GCS direct upload — allow the browser to PUT image bytes straight
  # to the bucket (image body no longer flows through Cloud Run). Origins mirror
  # the frontend service URL / CORS_ORIGINS.
  cors {
    origin          = [local.frontend_url, "http://localhost:5173"]
    method          = ["PUT", "GET", "HEAD", "OPTIONS"]
    response_header = ["Content-Type", "x-goog-resumable"]
    max_age_seconds = 3600
  }

  depends_on = [google_project_service.services]
}
