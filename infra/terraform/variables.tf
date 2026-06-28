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

variable "upload_function_name" {
  description = "gen2 upload Cloud Function name. Matches secret CLOUD_FUNCTION_UPLOAD."
  type        = string
  default     = "toddler-private-rag-upload"
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
# changes (see lifecycle in cloud_run.tf / cloud_function.tf), so these defaults
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

# --- Upload Cloud Function source (managed by the gcloud deploy; ignored). ---

variable "function_source_bucket" {
  description = "GCS bucket holding the gen2 function source zip. Empty = derive gcf-v2-sources-<project_number>-<region>."
  type        = string
  default     = ""
}

variable "function_source_object" {
  description = "Object path of the gen2 function source zip. Ignored after import."
  type        = string
  default     = "toddler-private-rag-upload/source.zip"
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
  description = "Value of the worker invoke token (rag-worker-invoke-token) sent by Cloud Scheduler as the X-Worker-Token header. Sensitive; supply via terraform.tfvars (gitignored). Managed out-of-band like the other secret values."
  type        = string
  default     = ""
  sensitive   = true
}
