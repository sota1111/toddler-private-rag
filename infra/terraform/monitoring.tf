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

# SOT-1472: log-based metrics for LLM (Gemini) calls. The backend emits one log
# line per LLM call containing the token "llm_call" (all calls) and, on failure,
# "llm_call_failed" (see backend/app/ai_client.py:log_llm_call). These metrics
# feed the ops dashboard (dashboard.tf) and the LLM error-rate alert below.
resource "google_logging_metric" "llm_request_count" {
  project     = var.project_id
  name        = "llm_request_count"
  description = "Count of LLM (Gemini) calls emitted by the backend (SOT-1472)."
  filter      = "resource.type=\"cloud_run_revision\" AND textPayload:\"llm_call\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.services]
}

resource "google_logging_metric" "llm_error_count" {
  project     = var.project_id
  name        = "llm_error_count"
  description = "Count of failed LLM (Gemini) calls emitted by the backend (SOT-1472)."
  filter      = "resource.type=\"cloud_run_revision\" AND textPayload:\"llm_call_failed\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.services]
}

# Alert: high LLM error rate (SOT-1472).
resource "google_monitoring_alert_policy" "llm_error_rate" {
  project      = var.project_id
  display_name = "LLM error rate high (SOT-1472)"
  combiner     = "OR"

  conditions {
    display_name = "LLM call failures per second"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"logging.googleapis.com/user/llm_error_count\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.llm_error_rate_threshold
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = google_monitoring_notification_channel.email[*].id

  documentation {
    content   = "The backend LLM (Gemini) call failure rate exceeds the configured threshold. Check backend logs (filter: llm_call_failed), Vertex AI quota, and consider rolling back (see docs/runbook-rollback.md, docs/runbook-operations.md)."
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.llm_error_count]
}
