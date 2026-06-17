#!/usr/bin/env bash
set -euo pipefail

# ローカル gcloud CLI 認証による Cloud Run デプロイスクリプト
# (toddler-private-rag)
#
# 使い方:
#   cp .env.example .env && vi .env
#   source .env && bash scripts/deploy_local_gcp.sh

if [ -f .env ]; then set -a; source .env; set +a; fi

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE_NAME="${CLOUD_RUN_SERVICE_NAME:-toddler-private-rag-backend}"
ARTIFACT_REPO="${ARTIFACT_REGISTRY_REPOSITORY:-toddler-rag-registry}"
IMAGE_VAR="${IMAGE_NAME:-toddler-private-rag-backend}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${IMAGE_VAR}"

echo "== Cloud Run デプロイ: ${SERVICE_NAME} =="
echo "Project: ${PROJECT_ID} | Region: ${REGION}"

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

gcloud artifacts repositories describe "${ARTIFACT_REPO}" \
  --project="${PROJECT_ID}" --location="${REGION}" &>/dev/null || \
gcloud artifacts repositories create "${ARTIFACT_REPO}" \
  --project="${PROJECT_ID}" --location="${REGION}" \
  --repository-format=docker \
  --description="Toddler Private RAG Docker images"

gcloud builds submit ./backend \
  --project="${PROJECT_ID}" \
  --tag="${IMAGE}:latest" \
  --timeout=600s


# Secret Manager: 初回デプロイ前に以下を実行してください
# echo -n "value" | gcloud secrets create rag-auth-secret --data-file=- --project=$PROJECT_ID
# echo -n "value" | gcloud secrets create rag-allowed-emails --data-file=- --project=$PROJECT_ID
# gcloud projects add-iam-policy-binding $PROJECT_ID \
#   --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"

gcloud run deploy "${SERVICE_NAME}" \
  --set-secrets="AUTH_SECRET=rag-auth-secret:latest,ALLOWED_USER_EMAILS=rag-allowed-emails:latest" \
  --set-env-vars="APP_ENV=production" \
  --image="${IMAGE}:latest" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --memory=512Mi \
  --timeout=300 \
  --quiet

URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --format='value(status.url)')

echo "== デプロイ完了 =="
echo "Service URL: ${URL}"
