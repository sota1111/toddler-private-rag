# SOT-1486 (SRE first wave): formal SLOs + error budget (A1) and synthetic
# uptime monitoring (A3) for the backend Cloud Run service.
#
# Prior monitoring (monitoring.tf) was threshold-alert-only; the hackathon
# submission itself noted "no formal SLO value is defined". This file adds:
#   A1 - a custom monitoring service with request-based availability and latency
#        SLOs over a rolling 28-day window, which produce an error budget and
#        burn-down that Cloud Monitoring tracks automatically.
#   A3 - an HTTPS uptime check against the backend /health endpoint plus an alert,
#        so a full outage is detected even at low traffic (the existing 5xx /
#        latency alerts are request-traffic dependent).
#
# IaC-only, application unchanged. Multi-window burn-rate alerting (A2), SLO
# burn-down dashboard tiles (C7), and probes for the other services are natural
# follow-ups tracked separately.

# --- A1: SLO + error budget ---------------------------------------------------

# Custom monitoring service the SLOs attach to. Represents the backend Cloud Run
# service for SLO tracking (basic_sli auto-detection is not used so the SLIs can
# reference the backend's request metrics explicitly).
resource "google_monitoring_custom_service" "backend" {
  project      = var.project_id
  service_id   = "toddler-backend-slo"
  display_name = "toddler-private-rag backend (SLO)"

  depends_on = [google_project_service.services]
}

# Availability SLO: fraction of backend requests that are NOT 5xx, over 28 days.
resource "google_monitoring_slo" "backend_availability" {
  project      = var.project_id
  service      = google_monitoring_custom_service.backend.service_id
  slo_id       = "backend-availability"
  display_name = "Backend availability (non-5xx) - rolling 28d"

  goal                = var.slo_availability_goal
  rolling_period_days = 28

  request_based_sli {
    good_total_ratio {
      total_service_filter = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" resource.label.\"service_name\"=\"${var.backend_service_name}\""
      bad_service_filter   = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" resource.label.\"service_name\"=\"${var.backend_service_name}\" metric.label.\"response_code_class\"=\"5xx\""
    }
  }
}

# Latency SLO: fraction of backend requests served under the latency threshold.
resource "google_monitoring_slo" "backend_latency" {
  project      = var.project_id
  service      = google_monitoring_custom_service.backend.service_id
  slo_id       = "backend-latency"
  display_name = "Backend request latency under threshold - rolling 28d"

  goal                = var.slo_latency_goal
  rolling_period_days = 28

  request_based_sli {
    distribution_cut {
      distribution_filter = "metric.type=\"run.googleapis.com/request_latencies\" resource.type=\"cloud_run_revision\" resource.label.\"service_name\"=\"${var.backend_service_name}\""

      range {
        max = var.slo_latency_threshold_ms
      }
    }
  }
}

# --- A3: synthetic uptime monitoring -----------------------------------------

# HTTPS uptime check against the backend /health endpoint. host is derived from
# the actual service URI so it tracks the deployed URL format.
resource "google_monitoring_uptime_check_config" "backend_health" {
  project      = var.project_id
  display_name = "Backend /health uptime (SOT-1486 A3)"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = replace(google_cloud_run_v2_service.backend.uri, "https://", "")
    }
  }

  depends_on = [google_project_service.services]
}

# Alert when the uptime check fails from multiple probers.
resource "google_monitoring_alert_policy" "backend_uptime" {
  project      = var.project_id
  display_name = "Backend /health uptime check failing (SOT-1486 A3)"
  combiner     = "OR"

  conditions {
    display_name = "backend /health uptime failures"

    condition_threshold {
      filter          = "resource.type = \"uptime_url\" AND metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id = \"${google_monitoring_uptime_check_config.backend_health.uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "60s"

      aggregations {
        alignment_period     = "1200s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.alert_notification_channels

  documentation {
    content   = "The backend /health uptime check is failing from multiple locations, indicating a full outage (this fires even at zero request traffic, unlike the 5xx/latency alerts). Check the service, recent deploys, and consider rolling back (see docs/runbook-rollback.md, docs/runbook-operations.md)."
    mime_type = "text/markdown"
  }

  depends_on = [google_monitoring_uptime_check_config.backend_health]
}
