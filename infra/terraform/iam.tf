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

# --- Optional: dedicated least-privilege RUNTIME service account ---
#
# Current state: Cloud Run services and the upload function run as the project
# DEFAULT compute service account (the deploy workflow does not pass
# --service-account). That is why no runtime SA is created by default here and
# var.cloud_run_service_account_email defaults to "".
#
# To harden (least privilege, see the architecture review), uncomment the block
# below, set var.cloud_run_service_account_email to its email, then redeploy so
# the services adopt it.
#
# resource "google_service_account" "runtime" {
#   project      = var.project_id
#   account_id   = "toddler-run-runtime"
#   display_name = "toddler-private-rag Cloud Run runtime"
# }
#
# locals {
#   runtime_sa_roles = [
#     "roles/secretmanager.secretAccessor",
#     "roles/datastore.user",
#     "roles/storage.objectAdmin",
#     "roles/aiplatform.user",
#   ]
# }
#
# resource "google_project_iam_member" "runtime" {
#   for_each = toset(local.runtime_sa_roles)
#   project  = var.project_id
#   role     = each.value
#   member   = "serviceAccount:${google_service_account.runtime.email}"
# }
