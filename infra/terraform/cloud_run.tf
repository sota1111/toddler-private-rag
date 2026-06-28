# Cloud Run services: backend (AI worker) and frontend. Settings mirror
# .github/workflows/deploy-cloudrun.yml. Container images are pushed by CI, so
# Terraform ignores image (and the gcloud-set client metadata) to avoid fighting
# the deploy workflow.

locals {
  # Default *.run.app URL of the frontend service, used for CORS just like the
  # workflow constructs it.
  frontend_url = "https://${var.frontend_service_name}-${var.project_number}.${var.region}.run.app"

  runtime_sa = var.cloud_run_service_account_email != "" ? var.cloud_run_service_account_email : null
}

resource "google_cloud_run_v2_service" "backend" {
  project             = var.project_id
  name                = var.backend_service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    timeout         = "300s"
    service_account = local.runtime_sa

    containers {
      image = var.backend_image

      resources {
        limits = {
          memory = "512Mi"
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
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.gemini_location
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
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
        name = "AUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["rag-auth-secret"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ALLOWED_USER_EMAILS"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["rag-allowed-emails"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "FIREBASE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["rag-firebase-api-key"].secret_id
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

resource "google_cloud_run_v2_service" "frontend" {
  project             = var.project_id
  name                = var.frontend_service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    timeout         = "300s"
    service_account = local.runtime_sa

    containers {
      image = var.frontend_image

      resources {
        limits = {
          memory = "256Mi"
        }
      }

      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
      env {
        name  = "UPLOAD_URL"
        value = google_cloudfunctions2_function.upload.service_config[0].uri
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

# allow-unauthenticated: public invoke on both services.
resource "google_cloud_run_v2_service_iam_member" "backend_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
