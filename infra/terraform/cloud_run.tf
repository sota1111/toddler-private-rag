# Cloud Run services: backend (AI worker) and frontend. Settings mirror
# .github/workflows/deploy-cloudrun.yml. Container images are pushed by CI, so
# Terraform ignores image (and the gcloud-set client metadata) to avoid fighting
# the deploy workflow.

locals {
  # Default *.run.app URL of the frontend service, used for CORS just like the
  # workflow constructs it.
  frontend_url = "https://${var.frontend_service_name}-${var.project_number}.${var.region}.run.app"

  runtime_sa  = var.cloud_run_service_account_email != "" ? var.cloud_run_service_account_email : null
  frontend_sa = var.frontend_service_account_email != "" ? var.frontend_service_account_email : null
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

    # SOT-1366 item C: cap fan-out to protect cost / Vertex AI quota.
    # SOT-1374 item A: keep 1 warm instance to avoid cold-start latency on the backend.
    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }

    containers {
      image = var.backend_image

      resources {
        limits = {
          memory = "512Mi"
        }
      }

      # SOT-1486 B4: startup + liveness probes on /health. The backend exposes a
      # lightweight GET /health (backend/app/main.py) that returns static ok with
      # no external calls, so it is safe to poll. The startup probe gates traffic
      # until the container is ready (cold-start / warm-up tolerance); the liveness
      # probe restarts a hung container. CI (deploy-cloudrun.yml) only sets the
      # image/env, so gcloud preserves these Terraform-managed probes across deploys.
      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 0
        timeout_seconds       = 5
        period_seconds        = 10
        failure_threshold     = 6
      }
      liveness_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 10
        timeout_seconds       = 5
        period_seconds        = 30
        failure_threshold     = 3
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
      # SOT-1377: GCS direct upload の V4 署名(キーレス signBlob)で使う署名 SA。
      # runtime SA 自身を指定する（runtime SA には自分への serviceAccountTokenCreator が必要）。
      env {
        name  = "GCS_SIGNER_SA_EMAIL"
        value = var.cloud_run_service_account_email
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
    service_account = local.frontend_sa

    # SOT-1366 item C: cap fan-out to protect cost.
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

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
        value = google_cloud_run_v2_service.upload.uri
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
