output "backend_url" {
  description = "Cloud Run backend (AI worker) URL."
  value       = google_cloud_run_v2_service.backend.uri
}

output "frontend_url" {
  description = "Cloud Run frontend URL."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "upload_url" {
  description = "Cloud Run upload-api service URL (SOT-1376)."
  value       = google_cloud_run_v2_service.upload.uri
}

output "deploy_service_account_email" {
  description = "GitHub Actions deploy service account email."
  value       = google_service_account.deploy.email
}

output "runtime_service_account_email" {
  description = "Backend/function runtime SA email (set as GitHub secret CLOUD_RUN_RUNTIME_SA)."
  value       = google_service_account.runtime.email
}

output "frontend_service_account_email" {
  description = "Frontend runtime SA email (set as GitHub secret CLOUD_RUN_FRONTEND_SA)."
  value       = google_service_account.frontend.email
}

output "attachments_bucket" {
  description = "GCS bucket for attachments."
  value       = google_storage_bucket.attachments.name
}

output "artifact_registry_repository" {
  description = "Artifact Registry docker repository ID."
  value       = google_artifact_registry_repository.docker.repository_id
}

output "workload_identity_pool_provider" {
  description = "Full WIF provider resource name (set as GitHub secret GCP_WORKLOAD_IDENTITY_PROVIDER)."
  value       = google_iam_workload_identity_pool_provider.github.name
}
