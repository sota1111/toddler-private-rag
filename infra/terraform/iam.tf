# --- GitHub Actions deploy service account ---
# Used by the deploy workflow (secret GCP_SERVICE_ACCOUNT) via Workload Identity
# Federation. Already exists in GCP -> import it.

resource "google_service_account" "deploy" {
  project      = var.project_id
  account_id   = var.deploy_service_account_id
  display_name = "GitHub Actions deployer (toddler-private-rag)"

  depends_on = [google_project_service.services]
}

# Project roles the deploy SA needs to build/push images and deploy Cloud Run +
# Cloud Functions. google_project_iam_member is non-authoritative: it manages
# only these specific bindings and never strips other members. Import the ones
# that already exist; `terraform apply` simply creates any that are missing.
locals {
  deploy_sa_roles = [
    "roles/run.admin",
    "roles/cloudfunctions.admin",
    "roles/artifactregistry.writer",
    "roles/iam.serviceAccountUser",
    "roles/storage.admin",
    "roles/secretmanager.admin",
  ]
}

resource "google_project_iam_member" "deploy" {
  for_each = toset(local.deploy_sa_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# --- Dedicated least-privilege RUNTIME service accounts (SOT-1366 / item A) ---
#
# Hardening over the previous state, where Cloud Run services and the upload
# function ran as the project DEFAULT compute service account (≈ Editor). Two
# SAs are used:
#   * runtime  — backend (AI worker) + upload function. Needs Secret Manager,
#     Firestore, GCS, Vertex AI, plus log/metric writing.
#   * frontend — nginx only; no data-plane roles, just log/metric writing.
#
# The deploy workflow passes these via --service-account (secrets
# CLOUD_RUN_RUNTIME_SA / CLOUD_RUN_FRONTEND_SA). Terraform wires them through
# var.cloud_run_service_account_email / var.frontend_service_account_email.

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "toddler-run-runtime"
  display_name = "toddler-private-rag Cloud Run / function runtime"

  depends_on = [google_project_service.services]
}

resource "google_service_account" "frontend" {
  project      = var.project_id
  account_id   = "toddler-run-frontend"
  display_name = "toddler-private-rag frontend (nginx) runtime"

  depends_on = [google_project_service.services]
}

locals {
  runtime_sa_roles = [
    "roles/secretmanager.secretAccessor",
    "roles/datastore.user",
    "roles/storage.objectAdmin",
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ]

  # The frontend only needs to emit logs/metrics; no data-plane access.
  frontend_sa_roles = [
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ]
}

resource "google_project_iam_member" "runtime" {
  for_each = toset(local.runtime_sa_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "frontend" {
  for_each = toset(local.frontend_sa_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.frontend.email}"
}

# The deploy SA must be able to actAs the runtime SAs to deploy services that
# run as them (otherwise: PERMISSION_DENIED iam.serviceaccounts.actAs).
resource "google_service_account_iam_member" "deploy_act_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_service_account_iam_member" "deploy_act_as_frontend" {
  service_account_id = google_service_account.frontend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

# SOT-1377: GCS direct upload の V4 署名(キーレス signBlob)。Cloud Run の runtime SA は
# 秘密鍵を持たないため、自分自身に対する serviceAccountTokenCreator を付与し、IAM
# signBlob 経由で署名付き PUT URL を発行できるようにする。
resource "google_service_account_iam_member" "runtime_sign_self" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}
