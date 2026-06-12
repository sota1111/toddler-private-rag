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

gcloud run deploy "${SERVICE_NAME}" \
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
