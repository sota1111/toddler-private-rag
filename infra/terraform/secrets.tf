# Secret Manager secret CONTAINERS only.
#
# Terraform deliberately does NOT manage google_secret_manager_secret_version:
# the secret VALUES (auth secret, allowed emails, Firebase API key, worker
# invoke token) are sensitive and are managed manually / out-of-band. Adding a
# secret version here would put plaintext into state and the repo.

locals {
  secret_ids = [
    "rag-auth-secret",
    "rag-allowed-emails",
    "rag-firebase-api-key",
    "rag-worker-invoke-token",
  ]
}

resource "google_secret_manager_secret" "secrets" {
  for_each = toset(local.secret_ids)

  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}
