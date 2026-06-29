# SOT-1377: GCS direct upload — OBJECT_FINALIZE event delivery.
#
# Browser uploads image bytes straight to GCS (under the `uploads/direct/`
# prefix). On finalize, GCS publishes to a Pub/Sub topic, which pushes to the
# backend's worker-token-protected `/internal/gcs-finalize` endpoint. The
# endpoint reconciles the object against Firestore metadata and starts OCR
# idempotently (pending→processing CAS), so duplicate Pub/Sub deliveries are
# absorbed.
#
# Import-only (SOT-1361): these resources already exist live (created via
# gcloud/gsutil). Run `terraform import` per infra/terraform/README.md; do NOT
# `terraform apply` against the live project.

resource "google_pubsub_topic" "gcs_finalize" {
  project = var.project_id
  name    = var.gcs_finalize_topic

  depends_on = [google_project_service.services]
}

# GCS service agent must be allowed to publish notifications to the topic.
data "google_storage_project_service_account" "gcs" {
  project = var.project_id
}

resource "google_pubsub_topic_iam_member" "gcs_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.gcs_finalize.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

# Fire only for objects written under the direct-upload prefix so the legacy
# multipart upload path (uploads/ root, which dispatches OCR synchronously) does
# not trigger a second OCR.
resource "google_storage_notification" "gcs_finalize" {
  bucket             = google_storage_bucket.attachments.name
  topic              = google_pubsub_topic.gcs_finalize.id
  payload_format     = "JSON_API_V1"
  event_types        = ["OBJECT_FINALIZE"]
  object_name_prefix = "uploads/direct/"

  depends_on = [google_pubsub_topic_iam_member.gcs_publisher]
}

# Push subscription → backend finalize endpoint. The worker token is sensitive
# and supplied via the `worker_invoke_token` variable (same out-of-band policy
# as scheduler.tf); push_config is under ignore_changes so a value set via
# gcloud is not overwritten.
resource "google_pubsub_subscription" "gcs_finalize_push" {
  project = var.project_id
  name    = "${var.gcs_finalize_topic}-push"
  topic   = google_pubsub_topic.gcs_finalize.id

  ack_deadline_seconds = 60

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.backend.uri}/internal/gcs-finalize?token=${var.worker_invoke_token}"
  }

  lifecycle {
    ignore_changes = [
      push_config,
    ]
  }

  depends_on = [google_project_service.services]
}
