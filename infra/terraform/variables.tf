# Input variables.
#
# Variables WITH a default are public, non-secret literals taken from
# .github/workflows/deploy-cloudrun.yml. Variables WITHOUT a default must be
# supplied via terraform.tfvars (copy terraform.tfvars.example) because their
# value is not stored in the repo (it lives in GitHub Actions secrets / GCP).

variable "project_id" {
  description = "GCP project ID."
  type        = string
  default     = "gen-lang-client-0243034020"
}

variable "project_number" {
  description = "GCP project number. Used to build the default Cloud Run *.run.app URL for CORS. Find with: gcloud projects describe <project_id> --format='value(projectNumber)'."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud Functions, Artifact Registry."
  type        = string
  default     = "asia-northeast1"
}

variable "gcs_bucket_location" {
  description = "Location of the attachments GCS bucket."
  type        = string
  default     = "ASIA-NORTHEAST1"
}

variable "firestore_location" {
  description = "Firestore database location."
  type        = string
  default     = "asia-northeast1"
}

# --- Resource names (these are GitHub Actions secrets today; confirm the real
# values against GCP before importing — defaults are best-guess slugs). ---

variable "artifact_registry_repository" {
  description = "Artifact Registry repository ID (docker). Matches secret ARTIFACT_REGISTRY_REPOSITORY."
  type        = string
  default     = "toddler-private-rag"
}

variable "backend_service_name" {
  description = "Cloud Run backend (AI worker) service name. Matches secret CLOUD_RUN_SERVICE_BACKEND."
  type        = string
  default     = "toddler-private-rag-backend"
}

variable "frontend_service_name" {
  description = "Cloud Run frontend service name. Matches secret CLOUD_RUN_SERVICE_FRONTEND."
  type        = string
  default     = "toddler-private-rag-frontend"
}

variable "upload_service_name" {
  description = "Cloud Run upload-api service name (SOT-1376). Matches secret CLOUD_RUN_SERVICE_UPLOAD."
  type        = string
  default     = "upload-api"
}

variable "gcs_bucket_name" {
  description = "GCS bucket for attachment files."
  type        = string
  default     = "gen-lang-client-0243034020-toddler-private-rag"
}

# --- Vertex AI / Gemini (env vars on the backend & upload services). ---

variable "gemini_model" {
  description = "GEMINI_MODEL env value."
  type        = string
  default     = "gemini-3.5-flash"
}

variable "gemini_location" {
  description = "GOOGLE_CLOUD_LOCATION env value for Vertex AI."
  type        = string
  default     = "global"
}

# --- Container images. CI builds & pushes these; Terraform ignores image
# changes (see lifecycle in cloud_run.tf / cloud_run_upload.tf), so these defaults
# are only used on first create/import. ---

variable "backend_image" {
  description = "Backend container image. Overridden by CI pushes (ignored by Terraform)."
  type        = string
  default     = ""
}

variable "frontend_image" {
  description = "Frontend container image. Overridden by CI pushes (ignored by Terraform)."
  type        = string
  default     = ""
}

variable "upload_image" {
  description = "upload-api container image. Overridden by CI pushes (ignored by Terraform)."
  type        = string
  default     = ""
}

# --- CI deploy identity: Workload Identity Federation + deploy service account. ---

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to assume the deploy SA via WIF, e.g. sota1111/toddler-private-rag."
  type        = string
}

variable "wif_pool_id" {
  description = "Workload Identity Pool ID (the short id, not the full resource path)."
  type        = string
}

variable "wif_provider_id" {
  description = "Workload Identity Pool Provider ID (the short id)."
  type        = string
}

variable "deploy_service_account_id" {
  description = "Account id (the part before @) of the GitHub Actions deploy service account."
  type        = string
}

variable "cloud_run_service_account_email" {
  description = "Runtime service account email for the backend Cloud Run service and the upload function (least privilege, see iam.tf). Empty = project default compute SA. Set to google_service_account.runtime.email after the SA exists."
  type        = string
  default     = ""
}

variable "frontend_service_account_email" {
  description = "Runtime service account email for the frontend (nginx) Cloud Run service. Empty = project default compute SA. Set to google_service_account.frontend.email after the SA exists."
  type        = string
  default     = ""
}

# --- SOT-1366 item B: orphan-attachment cleanup scheduler. ---

variable "orphan_purge_schedule" {
  description = "Cron schedule (Asia/Tokyo) for the daily orphan-attachment cleanup job."
  type        = string
  default     = "0 3 * * *"
}

variable "worker_invoke_token" {
  description = "Value of the worker invoke token (rag-worker-invoke-token) sent by Cloud Scheduler as the X-Worker-Token header and as the ?token= query of the Pub/Sub push subscription (SOT-1377). Sensitive; supply via terraform.tfvars (gitignored). Managed out-of-band like the other secret values."
  type        = string
  default     = ""
  sensitive   = true
}

variable "gcs_finalize_topic" {
  description = "SOT-1377: Pub/Sub topic name for GCS direct-upload OBJECT_FINALIZE events."
  type        = string
  default     = "toddler-gcs-finalize"
}

# --- SOT-1400: Cloud Monitoring alerting. ---

variable "alert_notification_email" {
  description = "Email address for Cloud Monitoring alert notifications. Empty = no email channel is created (alert policies still exist, just without a notification channel)."
  type        = string
  default     = ""
}

variable "cloud_run_5xx_threshold" {
  description = "SOT-1400: 5xx response rate (requests/second, aligned) above which the high-error-rate alert fires."
  type        = number
  default     = 0.1
}

variable "cloud_run_latency_threshold_ms" {
  description = "SOT-1400: p99 request latency (milliseconds) above which the high-latency alert fires."
  type        = number
  default     = 2000
}

variable "llm_error_rate_threshold" {
  description = "SOT-1472: LLM (Gemini) call failure rate (failures/second, aligned) above which the LLM-error alert fires."
  type        = number
  default     = 0.05
}

variable "llm_grounding_degraded_rate_threshold" {
  description = "SOT-1470 D3: rate (per second, aligned) of grounding-degradation events (grounded request falling back to non-grounded) above which the degradation alert fires."
  type        = number
  default     = 0.1
}

# --- SOT-1486 (SRE first wave): SLOs + error budget. ---

variable "slo_availability_goal" {
  description = "SOT-1486 A1: target fraction of backend requests that are non-5xx over the rolling 28-day window (availability SLO)."
  type        = number
  default     = 0.995
}

variable "slo_latency_goal" {
  description = "SOT-1486 A1: target fraction of backend requests served under slo_latency_threshold_ms over the rolling 28-day window (latency SLO)."
  type        = number
  default     = 0.95
}

variable "slo_latency_threshold_ms" {
  description = "SOT-1486 A1: request latency (milliseconds) that defines a 'good' (fast enough) request for the latency SLO."
  type        = number
  default     = 2000
}

# --- SOT-1480 (P2): autonomous runtime rollback (remediation service). ---
# Opt-in and safe by default: with enable_autonomous_rollback = false NOTHING new is created,
# and the alert policies keep notifying only the email channel. Flip it on (plus set a token and
# deploy the image via CI) to route alerts to the remediation service.

variable "enable_autonomous_rollback" {
  description = "SOT-1480 P2: create the remediation Cloud Run service + webhook notification channel and wire the Cloud Run alerts to it. Default false = nothing new is created (safe/opt-in)."
  type        = bool
  default     = false
}

variable "remediation_service_name" {
  description = "SOT-1480: Cloud Run service name for the autonomous rollback remediation service."
  type        = string
  default     = "toddler-remediation"
}

variable "remediation_image" {
  description = "SOT-1480: remediation container image. Overridden by CI pushes (ignored by Terraform); only used on first create."
  type        = string
  default     = ""
}

variable "remediation_token" {
  description = "SOT-1480: shared token embedded in the webhook URL and required by the remediation service (?token=). Sensitive; supply via terraform.tfvars (gitignored)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "remediation_dry_run" {
  description = "SOT-1480: when true the remediation service computes and logs the rollback decision but never shifts traffic. Default true (safe)."
  type        = bool
  default     = true
}

variable "remediation_cooldown_seconds" {
  description = "SOT-1480: minimum seconds between automatic rollbacks of the same service."
  type        = number
  default     = 3600
}

variable "remediation_deploy_window_seconds" {
  description = "SOT-1480: only auto-roll-back when the currently-serving revision is younger than this many seconds (recent-deploy attribution)."
  type        = number
  default     = 3600
}

variable "remediation_allowed_services" {
  description = "SOT-1480: optional comma-separated allowlist of Cloud Run services eligible for autonomous rollback. Empty = all services are eligible."
  type        = string
  default     = ""
}
