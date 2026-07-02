# SOT-1480 (P2): autonomous runtime rollback.
#
# The "runtime version" of the deploy-time canary rollback in
# .github/workflows/deploy-cloudrun.yml (SOT-1469 B2). A Cloud Monitoring alert
# (monitoring.tf: 5xx / latency / LLM error) fires the `remediation_webhook`
# notification channel, which POSTs the incident to this small remediation Cloud Run
# service. The service (backend/remediation_function) decides — with guardrails
# (token auth, dry-run default-on, cooldown, recent-deploy attribution) — whether to
# shift Cloud Run traffic back to the previous healthy revision.
#
# OPT-IN / SAFE BY DEFAULT: everything here is count-gated on
# var.enable_autonomous_rollback. With the default (false) NOTHING new is created and
# the alerts keep notifying only the email channel.

locals {
  remediation_enabled = var.enable_autonomous_rollback ? 1 : 0
}

# Dedicated least-privilege service account for the remediation service.
resource "google_service_account" "remediation" {
  count        = local.remediation_enabled
  project      = var.project_id
  account_id   = "toddler-remediation"
  display_name = "toddler-private-rag autonomous rollback (SOT-1480)"

  depends_on = [google_project_service.services]
}

locals {
  remediation_sa_roles = [
    "roles/run.developer",  # update-traffic on Cloud Run services
    "roles/datastore.user", # cooldown state in Firestore
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ]
}

resource "google_project_iam_member" "remediation" {
  for_each = var.enable_autonomous_rollback ? toset(local.remediation_sa_roles) : toset([])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.remediation[0].email}"
}

# The deploy SA must actAs the remediation SA to deploy the service running as it.
resource "google_service_account_iam_member" "deploy_act_as_remediation" {
  count = local.remediation_enabled

  service_account_id = google_service_account.remediation[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_cloud_run_v2_service" "remediation" {
  count    = local.remediation_enabled
  project  = var.project_id
  name     = var.remediation_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.remediation[0].email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      # CI builds & pushes the real image; Terraform ignores image changes (lifecycle
      # below), so this default is only used on first create.
      image = var.remediation_image != "" ? var.remediation_image : "us-docker.pkg.dev/cloudrun/container/hello"

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "REMEDIATION_DRY_RUN"
        value = tostring(var.remediation_dry_run)
      }
      env {
        name  = "REMEDIATION_TOKEN"
        value = var.remediation_token
      }
      env {
        name  = "REMEDIATION_COOLDOWN_SECONDS"
        value = tostring(var.remediation_cooldown_seconds)
      }
      env {
        name  = "REMEDIATION_DEPLOY_WINDOW_SECONDS"
        value = tostring(var.remediation_deploy_window_seconds)
      }
      env {
        name  = "REMEDIATION_ALLOWED_SERVICES"
        value = var.remediation_allowed_services
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.services]
}

# Webhook notification channel -> remediation service. The token is embedded in the URL
# (webhook_tokenauth) and validated by the service (?token=), matching the worker-token pattern.
resource "google_monitoring_notification_channel" "remediation_webhook" {
  count        = local.remediation_enabled
  project      = var.project_id
  display_name = "toddler-private-rag autonomous rollback webhook (SOT-1480)"
  type         = "webhook_tokenauth"

  labels = {
    url = "${google_cloud_run_v2_service.remediation[0].uri}/?token=${var.remediation_token}"
  }

  depends_on = [google_project_service.services]
}
