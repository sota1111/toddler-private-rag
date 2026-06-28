# SOT-1366 item B: daily orphan-attachment cleanup.
#
# Calls the backend's worker-token-protected endpoint, which deletes only GCS
# objects that have NO attachment DB record (orphans), older than the grace
# period. Currently-displayed photos are referenced in the DB and are never
# touched. Age-based deletion is deliberately NOT used.
#
# The X-Worker-Token value is sensitive and managed out-of-band (same policy as
# the Secret Manager values — see secrets.tf). It is supplied via the
# `worker_invoke_token` variable (terraform.tfvars, gitignored). headers are
# under ignore_changes so a value set out-of-band (gcloud) is not overwritten.

resource "google_cloud_scheduler_job" "purge_orphans" {
  project   = var.project_id
  region    = var.region
  name      = "toddler-private-rag-purge-orphans"
  schedule  = var.orphan_purge_schedule
  time_zone = "Asia/Tokyo"

  attempt_deadline = "320s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.backend.uri}/internal/purge-orphans"

    headers = {
      "Content-Type"   = "application/json"
      "X-Worker-Token" = var.worker_invoke_token
    }
  }

  lifecycle {
    ignore_changes = [
      http_target[0].headers,
    ]
  }

  depends_on = [google_project_service.services]
}
