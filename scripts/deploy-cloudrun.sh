#!/usr/bin/env bash
set -euo pipefail

# Cloud Run デプロイスクリプト (toddler-private-rag)
# 使い方:
#   GCP_PROJECT_ID=your-project-id \
#   bash scripts/deploy-cloudrun.sh

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
REGION="${REGION:-asia-northeast1}"
BACKEND_SERVICE="toddler-private-rag-backend"
FRONTEND_SERVICE="toddler-private-rag-frontend"
BACKEND_IMAGE="gcr.io/${PROJECT_ID}/${BACKEND_SERVICE}"
FRONTEND_IMAGE="gcr.io/${PROJECT_ID}/${FRONTEND_SERVICE}"

echo "== Cloud Run デプロイ: toddler-private-rag =="
echo "Project: ${PROJECT_ID} | Region: ${REGION}"

# Backend: Cloud Build でビルド & デプロイ
echo "--- Backend ---"
gcloud builds submit ./backend \
  --project="${PROJECT_ID}" \
  --tag="${BACKEND_IMAGE}" \
  --timeout=600s

# Secret Manager: 以下のシークレットが作成済みであることを前提としています
# rag-auth-secret, rag-allowed-emails, rag-firebase-api-key
#   rag-firebase-api-key: Firebase Web API key（サーバサイドREST認証 accounts:signInWithPassword 用）

gcloud run deploy "${BACKEND_SERVICE}" \
  --image="${BACKEND_IMAGE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --set-secrets="AUTH_SECRET=rag-auth-secret:latest,ALLOWED_USER_EMAILS=rag-allowed-emails:latest,FIREBASE_API_KEY=rag-firebase-api-key:latest" \
  --set-env-vars="APP_ENV=production,CORS_ORIGINS=https://${FRONTEND_SERVICE}-${PROJECT_ID}.a.run.app" \
  --memory=512Mi \
  --timeout=300 \
  --quiet

BACKEND_URL=$(gcloud run services describe "${BACKEND_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --format='value(status.url)' 2>/dev/null || echo "")

echo "Backend URL: ${BACKEND_URL:-N/A}"

# Frontend: Cloud Build でビルド & デプロイ
echo "--- Frontend ---"
gcloud builds submit ./frontend \
  --project="${PROJECT_ID}" \
  --tag="${FRONTEND_IMAGE}" \
  --timeout=600s

gcloud run deploy "${FRONTEND_SERVICE}" \
  --image="${FRONTEND_IMAGE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars="VITE_API_BASE_URL=${BACKEND_URL}" \
  --memory=256Mi \
  --timeout=300 \
  --quiet

echo ""
echo "== デプロイ完了 =="
