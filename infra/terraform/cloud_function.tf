# Upload Cloud Function (gen2). Slim, fast-booting, upload-only. Settings mirror
# the `gcloud functions deploy --gen2` step in deploy-cloudrun.yml. The function
# source zip is produced and uploaded by the gcloud deploy, so Terraform ignores
# build_config.source to avoid churn.

locals {
  function_source_bucket = var.function_source_bucket != "" ? var.function_source_bucket : "gcf-v2-sources-${var.project_number}-${var.region}"
}

resource "google_cloudfunctions2_function" "upload" {
  project  = var.project_id
  name     = var.upload_function_name
  location = var.region

  build_config {
    runtime     = "python311"
    entry_point = "upload_attachment"

    source {
      storage_source {
        bucket = local.function_source_bucket
        object = var.function_source_object
      }
    }
  }

  service_config {
    available_memory      = "256Mi"
    timeout_seconds       = 60
    service_account_email = local.runtime_sa

    environment_variables = {
      APP_ENV              = "production"
      CORS_ORIGINS         = local.frontend_url
      DATABASE_TYPE        = "firestore"
      STORAGE_BACKEND      = "gcs"
      GCS_BUCKET_NAME      = var.gcs_bucket_name
      GOOGLE_CLOUD_PROJECT = var.project_id
      AI_WORKER_URL        = google_cloud_run_v2_service.backend.uri
    }

    secret_environment_variables {
      key        = "AUTH_SECRET"
      project_id = var.project_id
      secret     = google_secret_manager_secret.secrets["rag-auth-secret"].secret_id
      version    = "latest"
    }
    secret_environment_variables {
      key        = "WORKER_INVOKE_TOKEN"
      project_id = var.project_id
      secret     = google_secret_manager_secret.secrets["rag-worker-invoke-token"].secret_id
      version    = "latest"
    }
  }

  lifecycle {
    ignore_changes = [
      build_config[0].source,
    ]
  }

  depends_on = [google_project_service.services]
}

# allow-unauthenticated: a gen2 function is backed by a Cloud Run service of the
# same name, so public access is granted via run.invoker to allUsers.
resource "google_cloud_run_v2_service_iam_member" "upload_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.upload.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
