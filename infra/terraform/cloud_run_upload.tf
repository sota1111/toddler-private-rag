# SOT-1376: upload-api Cloud Run service. Slim, always-warm, upload-only. Replaces the
# SOT-1359 gen2 Cloud Function. Same functions-framework app (backend/upload_function),
# now a Cloud Run service with min_instance_count = 1 so the upload entrypoint stays warm
# (cold-start mitigation). Settings mirror the upload-api deploy step in
# deploy-cloudrun.yml. The container image is built & pushed by CI, so Terraform ignores
# the image to avoid fighting the deploy workflow.

resource "google_cloud_run_v2_service" "upload" {
  project             = var.project_id
  name                = var.upload_service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    timeout         = "60s"
    service_account = local.runtime_sa

    # SOT-1376: keep 1 warm instance to avoid cold-start latency on photo upload.
    # SOT-1366 item C: cap fan-out.
    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }

    containers {
      image = var.upload_image

      resources {
        limits = {
          memory = "256Mi"
        }
      }

      env {
        name  = "APP_ENV"
        value = "production"
      }
      env {
        name  = "CORS_ORIGINS"
        value = local.frontend_url
      }
      env {
        name  = "DATABASE_TYPE"
        value = "firestore"
      }
      env {
        name  = "STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = var.gcs_bucket_name
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "AI_WORKER_URL"
        value = google_cloud_run_v2_service.backend.uri
      }

      env {
        name = "AUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["rag-auth-secret"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "WORKER_INVOKE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["rag-worker-invoke-token"].secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.services]
}

# allow-unauthenticated: public invoke (frontend nginx reverse-proxies same-origin).
resource "google_cloud_run_v2_service_iam_member" "upload_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.upload.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
