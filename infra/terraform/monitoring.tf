# SOT-1400: Cloud Monitoring alerting for the Cloud Run services.
#
# Provides operational visibility (DevOps practice uplift) over the backend,
# frontend and upload-api Cloud Run services:
#   - an OPTIONAL email notification channel (created only when
#     var.alert_notification_email is set, so `terraform apply` never fails on a
#     missing address), and
#   - alert policies for a high 5xx error rate and high p99 request latency.
#
# All policies cover every Cloud Run revision in the project (grouped by
# service_name) so newly added services are watched automatically.

# Optional email notification channel. count-gated: empty email => no channel.
resource "google_monitoring_notification_channel" "email" {
  count = var.alert_notification_email == "" ? 0 : 1

  project      = var.project_id
  display_name = "toddler-private-rag alerts email"
  type         = "email"

  labels = {
    email_address = var.alert_notification_email
  }

  depends_on = [google_project_service.services]
}

# Alert: high 5xx response rate on any Cloud Run service.
resource "google_monitoring_alert_policy" "cloud_run_5xx" {
  project      = var.project_id
  display_name = "Cloud Run 5xx error rate high (SOT-1400)"
  combiner     = "OR"

  conditions {
    display_name = "5xx responses across Cloud Run services"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.cloud_run_5xx_threshold
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.labels.service_name"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = google_monitoring_notification_channel.email[*].id

  documentation {
    content   = "A Cloud Run service is returning 5xx responses above the configured rate. Check service logs in Cloud Logging and consider rolling back (see docs/runbook-rollback.md)."
    mime_type = "text/markdown"
  }

  depends_on = [google_project_service.services]
}

# Alert: high p99 request latency on any Cloud Run service.
resource "google_monitoring_alert_policy" "cloud_run_latency" {
  project      = var.project_id
  display_name = "Cloud Run request latency high (SOT-1400)"
  combiner     = "OR"

  conditions {
    display_name = "p99 request latency across Cloud Run services"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_latencies\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.cloud_run_latency_threshold_ms
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_99"
        cross_series_reducer = "REDUCE_MEAN"
        group_by_fields      = ["resource.labels.service_name"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = google_monitoring_notification_channel.email[*].id

  documentation {
    content   = "A Cloud Run service p99 latency exceeds the configured threshold. Inspect cold starts / Vertex AI calls; consider rolling back (see docs/runbook-rollback.md)."
    mime_type = "text/markdown"
  }

  depends_on = [google_project_service.services]
}
