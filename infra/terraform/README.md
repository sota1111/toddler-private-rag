# Terraform IaC — toddler-private-rag (GCP)

This directory codifies the GCP infrastructure that is currently deployed
imperatively by `.github/workflows/deploy-cloudrun.yml`.

**The resources already exist in GCP.** This config is for adopting them under
Terraform via `terraform import`. Do **not** run `terraform apply` against a
fresh state without importing first — apply would try to create resources that
already exist and fail with "already exists".

## What is managed

| File | Resources |
|------|-----------|
| `apis.tf` | Required `google_project_service` APIs |
| `artifact_registry.tf` | Artifact Registry docker repository |
| `secrets.tf` | 4 Secret Manager secret **containers** (values managed manually, not by TF) |
| `storage.tf` | GCS attachments bucket |
| `firestore.tf` | Firestore native database `(default)` |
| `cloud_run.tf` | Cloud Run `backend` + `frontend` services (+ public invoker, scaling caps) |
| `cloud_run_upload.tf` | Cloud Run `upload-api` upload service, min-instances=1 (+ public invoker) (SOT-1376) |
| `iam.tf` | Deploy SA + project roles; dedicated least-privilege **runtime** + **frontend** SAs |
| `scheduler.tf` | Daily orphan-attachment cleanup Cloud Scheduler job (SOT-1366 item B) |
| `pubsub.tf` | GCS direct-upload finalize: Pub/Sub topic + GCS notification + push subscription (SOT-1377) |
| `wif.tf` | Workload Identity Federation pool/provider + SA binding |

### Not managed by Terraform (by design)
- **Secret values** — only the secret containers are managed. Versions/values stay manual.
- **Container images** — built/pushed/deployed by CI. `lifecycle.ignore_changes` keeps
  Terraform from reverting image changes, so the existing GitHub Actions workflow keeps
  working unchanged. **Do not delete `.github/workflows/deploy-cloudrun.yml`.**

## Relationship to the existing CI workflow

Terraform owns the **platform and service definitions**; CI owns **image builds and
rollouts**. After adopting Terraform:
- `git push main` → CI builds images and runs `gcloud run deploy` (backend, frontend,
  upload-api) to ship a new image (Terraform ignores the image, so no drift fight).
- Infra changes (memory, env, IAM, new resources) → edit `.tf`, `terraform plan`, `terraform apply`.

## Prerequisites
- Terraform >= 1.5
- `gcloud auth application-default login` with rights on `gen-lang-client-0243034020`
- (Optional but recommended) a GCS bucket for remote state — see the commented backend in `versions.tf`.

## Steps

1. **Configure variables**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # fill in project_number, github_repository, wif_pool_id, wif_provider_id,
   # deploy_service_account_id, and CONFIRM the resource-name defaults match GCP.
   ```
   Discover real names if unsure:
   ```bash
   gcloud run services list --project gen-lang-client-0243034020
   gcloud artifacts repositories list --project gen-lang-client-0243034020
   gcloud iam workload-identity-pools list --location global --project gen-lang-client-0243034020
   gcloud iam service-accounts list --project gen-lang-client-0243034020
   ```

2. **Init**
   ```bash
   terraform init
   ```

3. **Import existing resources** (before any apply). Replace the UPPERCASE
   placeholders with your values (`PROJECT_ID`=`gen-lang-client-0243034020`,
   `REGION`=`asia-northeast1`, etc.).

   ```bash
   # APIs (repeat for each in apis.tf local.required_apis)
   terraform import 'google_project_service.services["run.googleapis.com"]'            PROJECT_ID/run.googleapis.com
   terraform import 'google_project_service.services["cloudfunctions.googleapis.com"]' PROJECT_ID/cloudfunctions.googleapis.com
   # ... (artifactregistry, secretmanager, storage, firestore, iam, iamcredentials,
   #      aiplatform, cloudbuild, eventarc, cloudresourcemanager, sts)

   # Artifact Registry
   terraform import google_artifact_registry_repository.docker \
     projects/PROJECT_ID/locations/REGION/repositories/REPO

   # Secret containers
   terraform import 'google_secret_manager_secret.secrets["rag-auth-secret"]'        projects/PROJECT_ID/secrets/rag-auth-secret
   terraform import 'google_secret_manager_secret.secrets["rag-allowed-emails"]'     projects/PROJECT_ID/secrets/rag-allowed-emails
   terraform import 'google_secret_manager_secret.secrets["rag-firebase-api-key"]'   projects/PROJECT_ID/secrets/rag-firebase-api-key
   terraform import 'google_secret_manager_secret.secrets["rag-worker-invoke-token"]' projects/PROJECT_ID/secrets/rag-worker-invoke-token

   # GCS bucket
   terraform import google_storage_bucket.attachments BUCKET_NAME

   # Firestore
   terraform import google_firestore_database.default \
     projects/PROJECT_ID/databases/'(default)'

   # Cloud Run services (backend, frontend, upload-api)
   terraform import google_cloud_run_v2_service.backend  projects/PROJECT_ID/locations/REGION/services/BACKEND_SERVICE
   terraform import google_cloud_run_v2_service.frontend projects/PROJECT_ID/locations/REGION/services/FRONTEND_SERVICE
   terraform import google_cloud_run_v2_service.upload   projects/PROJECT_ID/locations/REGION/services/UPLOAD_SERVICE

   # Cloud Run invoker bindings (member tuple, space-separated)
   terraform import google_cloud_run_v2_service_iam_member.backend_invoker  "projects/PROJECT_ID/locations/REGION/services/BACKEND_SERVICE roles/run.invoker allUsers"
   terraform import google_cloud_run_v2_service_iam_member.frontend_invoker "projects/PROJECT_ID/locations/REGION/services/FRONTEND_SERVICE roles/run.invoker allUsers"
   terraform import google_cloud_run_v2_service_iam_member.upload_invoker   "projects/PROJECT_ID/locations/REGION/services/UPLOAD_SERVICE roles/run.invoker allUsers"

   # Deploy service account + WIF
   terraform import google_service_account.deploy \
     projects/PROJECT_ID/serviceAccounts/DEPLOY_SA_ID@PROJECT_ID.iam.gserviceaccount.com
   terraform import google_iam_workload_identity_pool.github \
     projects/PROJECT_ID/locations/global/workloadIdentityPools/POOL_ID
   terraform import google_iam_workload_identity_pool_provider.github \
     projects/PROJECT_ID/locations/global/workloadIdentityPools/POOL_ID/providers/PROVIDER_ID
   terraform import google_service_account_iam_member.deploy_wif \
     "projects/PROJECT_ID/serviceAccounts/DEPLOY_SA_ID@PROJECT_ID.iam.gserviceaccount.com roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/attribute.repository/OWNER/REPO"

   # Deploy SA project roles (repeat per role in iam.tf local.deploy_sa_roles)
   terraform import 'google_project_iam_member.deploy["roles/run.admin"]' \
     "PROJECT_ID roles/run.admin serviceAccount:DEPLOY_SA_ID@PROJECT_ID.iam.gserviceaccount.com"
   # ... cloudfunctions.admin, artifactregistry.writer, iam.serviceAccountUser,
   #     storage.admin, secretmanager.admin
   ```

   > Bindings that do not exist yet will fail to import — that is fine. Leave them
   > unimported; step 4's `apply` will create them. `google_project_iam_member` is
   > non-authoritative and won't remove other members.

4. **Reconcile and apply**
   ```bash
   terraform plan    # review drift; expect only additive/no-op changes after import
   terraform apply
   ```
   Investigate any *destroy/replace* in the plan before applying — that signals a
   mismatch between this config and the live resource (often a name/region/location
   value to fix in `terraform.tfvars`).

## SOT-1366 hardening (P1/P2)

This config now declares the architecture-review hardening items. They are
**deployed via the CI workflow** (the single source of rollout); Terraform keeps
the declarations in sync so `terraform import` + `plan` converge to no-op. Run
`terraform import` for the new resources below to bring them under state.

- **A — least-privilege runtime SAs (`iam.tf`).** `toddler-run-runtime`
  (backend + upload-api: secretAccessor / datastore.user / storage.objectAdmin
  / aiplatform.user / logging / monitoring) and `toddler-run-frontend` (nginx:
  logging / monitoring only). The workflow passes them via the GitHub secrets
  `CLOUD_RUN_RUNTIME_SA` / `CLOUD_RUN_FRONTEND_SA`. **Set those secrets** so the
  next deploy adopts the SAs (empty secret = keep the default compute SA).
- **C — scaling caps.** `max_instance_count = 5` on all Cloud Run services;
  `min_instance_count = 1` on backend and upload-api (always-warm), `0` on frontend.
  Mirrored in the workflow.
- **B — orphan cleanup (`scheduler.tf`).** Daily Cloud Scheduler POST to the
  backend `/internal/purge-orphans` (worker-token protected; the `/internal/*`
  routes are not under `/api`, so nginx never proxies them). It deletes only
  GCS objects with **no** attachment DB record, older than `ORPHAN_GRACE_DAYS`
  (default 1). Displayed photos (referenced in the DB) are never deleted; no
  age-based deletion is used. The `X-Worker-Token` value is sensitive — supply it
  via `worker_invoke_token` in the gitignored `terraform.tfvars`, or set it
  out-of-band (headers are under `ignore_changes`).
- **D — backend ingress restriction: NOT done (deferred).** The frontend (nginx)
  reverse-proxies `/api/*` to the backend over its public URL. Restricting the
  backend to `ingress=internal` needs a Serverless VPC connector; switching to
  authenticated invoker needs nginx to mint Google ID tokens. Both risk breaking
  production. The backend already enforces app-level auth (Cookie HMAC +
  `ALLOWED_USER_EMAILS`), which mitigates the public invoker.

Import the new resources (after the existing import steps):
```bash
terraform import google_service_account.runtime \
  projects/PROJECT_ID/serviceAccounts/toddler-run-runtime@PROJECT_ID.iam.gserviceaccount.com
terraform import google_service_account.frontend \
  projects/PROJECT_ID/serviceAccounts/toddler-run-frontend@PROJECT_ID.iam.gserviceaccount.com
# runtime/frontend project roles: repeat per role in local.runtime_sa_roles / local.frontend_sa_roles
terraform import 'google_project_iam_member.runtime["roles/secretmanager.secretAccessor"]' \
  "PROJECT_ID roles/secretmanager.secretAccessor serviceAccount:toddler-run-runtime@PROJECT_ID.iam.gserviceaccount.com"
# Cloud Scheduler job
terraform import google_cloud_scheduler_job.purge_orphans \
  projects/PROJECT_ID/locations/REGION/jobs/toddler-private-rag-purge-orphans
# new API
terraform import 'google_project_service.services["cloudscheduler.googleapis.com"]' \
  PROJECT_ID/cloudscheduler.googleapis.com

# --- SOT-1377: GCS direct upload (Pub/Sub finalize events) ---
terraform import 'google_project_service.services["pubsub.googleapis.com"]' \
  PROJECT_ID/pubsub.googleapis.com
terraform import google_pubsub_topic.gcs_finalize \
  projects/PROJECT_ID/topics/toddler-gcs-finalize
terraform import google_pubsub_subscription.gcs_finalize_push \
  projects/PROJECT_ID/subscriptions/toddler-gcs-finalize-push
# GCS notification id: bucket + the numeric notificationConfigs id from `gsutil notification list`
terraform import google_storage_notification.gcs_finalize \
  BUCKET_NAME/notificationConfigs/NOTIFICATION_ID
# GCS service agent → pubsub.publisher on the topic
terraform import google_pubsub_topic_iam_member.gcs_publisher \
  "projects/PROJECT_ID/topics/toddler-gcs-finalize roles/pubsub.publisher serviceAccount:service-PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com"
# runtime SA self-signBlob (keyless V4 signing)
terraform import google_service_account_iam_member.runtime_sign_self \
  "projects/PROJECT_ID/serviceAccounts/toddler-run-runtime@PROJECT_ID.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator serviceAccount:toddler-run-runtime@PROJECT_ID.iam.gserviceaccount.com"
```

SOT-1377 also adds a `cors` block to `google_storage_bucket.attachments` and a
`GCS_SIGNER_SA_EMAIL` env var on the backend service; both converge on the next
`terraform import` + `plan` of the already-imported bucket / backend resources.

## Notes
- This config was validated for structure only; `terraform validate` / `plan` against
  the real project must be run by a human with GCP credentials.
- SOT-1400: `monitoring.tf` adds Cloud Monitoring alert policies (Cloud Run 5xx rate,
  p99 latency) and an optional email notification channel (`alert_notification_email`).
  Rollback procedure for a bad Cloud Run deploy: see `docs/runbook-rollback.md`.
