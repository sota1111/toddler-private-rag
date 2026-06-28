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
| `cloud_run.tf` | Cloud Run `backend` + `frontend` services (+ public invoker) |
| `cloud_function.tf` | gen2 upload Cloud Function (+ public invoker) |
| `iam.tf` | Deploy service account + project role bindings (runtime SA optional) |
| `wif.tf` | Workload Identity Federation pool/provider + SA binding |

### Not managed by Terraform (by design)
- **Secret values** — only the secret containers are managed. Versions/values stay manual.
- **Container images** — built/pushed/deployed by CI. `lifecycle.ignore_changes` keeps
  Terraform from reverting image changes, so the existing GitHub Actions workflow keeps
  working unchanged. **Do not delete `.github/workflows/deploy-cloudrun.yml`.**
- **Function source zip** — produced by the `gcloud functions deploy` step; ignored.

## Relationship to the existing CI workflow

Terraform owns the **platform and service definitions**; CI owns **image builds and
rollouts**. After adopting Terraform:
- `git push main` → CI builds images and runs `gcloud run deploy` / `gcloud functions deploy`
  to ship a new image (Terraform ignores the image, so no drift fight).
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
   gcloud functions list --project gen-lang-client-0243034020 --gen2
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

   # Cloud Run services
   terraform import google_cloud_run_v2_service.backend  projects/PROJECT_ID/locations/REGION/services/BACKEND_SERVICE
   terraform import google_cloud_run_v2_service.frontend projects/PROJECT_ID/locations/REGION/services/FRONTEND_SERVICE

   # Cloud Run invoker bindings (member tuple, space-separated)
   terraform import google_cloud_run_v2_service_iam_member.backend_invoker  "projects/PROJECT_ID/locations/REGION/services/BACKEND_SERVICE roles/run.invoker allUsers"
   terraform import google_cloud_run_v2_service_iam_member.frontend_invoker "projects/PROJECT_ID/locations/REGION/services/FRONTEND_SERVICE roles/run.invoker allUsers"

   # Upload function (gen2) + its invoker (backed by a Cloud Run service of same name)
   terraform import google_cloudfunctions2_function.upload projects/PROJECT_ID/locations/REGION/functions/UPLOAD_FUNCTION
   terraform import google_cloud_run_v2_service_iam_member.upload_invoker "projects/PROJECT_ID/locations/REGION/services/UPLOAD_FUNCTION roles/run.invoker allUsers"

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

## Notes
- This config was validated for structure only; `terraform validate` / `plan` against
  the real project must be run by a human with GCP credentials.
- A dedicated least-privilege runtime service account is provided (commented) in
  `iam.tf` as a hardening step — see the architecture review notes on SOT-1361.
