# Worker Report — SOT-1359 (アップ機能を Google Cloud Functions に変更)

## Fallback Disclosure (Worker Non-Response Policy)
- Non-responsive worker: **Antigravity CLI**.
- Detected failure mode: OAuth authentication timed out — `scripts/ai/run_antigravity.sh` exited with non-response code `75` (interactive `agy` login could not complete in this non-interactive environment; report missing `## Next Action`).
- Also non-responsive: **Codex CLI** (usage-limit cooldown, exit `75`).
- Action: per the Worker Non-Response Fallback Policy, Claude Code performed the implementation directly. All Quality Gates still apply.

## Summary
Migrated photo upload from the lightweight Cloud Run upload service (SOT-1322) to a **gen2 Cloud Function**. Approved options A=gen2 / B=dedicated slim source `backend/upload_function/` / C=functions-framework(Flask) path-extract + Cookie HMAC / D=replace & remove the old Cloud Run upload service.

The new function reproduces the exact public contract of `routers/upload.py`: `POST /api/info/{info_id}/attachments`, multipart field `file`, optional `language` query (default `ja`), `auth_token` cookie HMAC auth, GCS save, Firestore pending attachment, best-effort AI-worker OCR dispatch, JSON response identical to `AttachmentResponse`. It is self-contained (no `backend/app` imports) with its own slim requirements.

## Changed Files
- `backend/upload_function/main.py` — NEW. functions-framework HTTP entry `upload_attachment` (path regex extract info_id, Cookie HMAC, multipart validation 10MB/type, GCS upload, Firestore `attachments` pending doc, worker dispatch, CORS w/ credentials + OPTIONS preflight, lazy GCS/Firestore clients).
- `backend/upload_function/requirements.txt` — NEW. slim deps (functions-framework / google-cloud-storage / google-cloud-firestore / requests).
- `backend/upload_function/.gcloudignore` — NEW. trims the function upload bundle.
- `.github/workflows/deploy-cloudrun.yml` — replaced the upload Cloud Run build/push/deploy block with a single `gcloud functions deploy --gen2` step; frontend `UPLOAD_URL` now resolved via `gcloud functions describe ... serviceConfig.uri`; uses new secret `CLOUD_FUNCTION_UPLOAD`.
- `frontend/nginx.conf` — comment-only: "upload Cloud Run service" → "upload Cloud Function" (behavior unchanged).
- removed `backend/app/upload_main.py`, `backend/app/routers/upload.py`, `backend/Dockerfile.upload`, `backend/requirements-upload.txt` (old Cloud Run upload service — D=置換).

## Commands Run
- (see Codex verification report `docs/ai/60_worker_codex_report.md`)

## Acceptance Criteria
- [x] `backend/upload_function/main.py` (functions-framework path extract + Cookie HMAC + GCS + Firestore + worker dispatch)
- [x] `backend/upload_function/requirements.txt` slim
- [x] deploy-cloudrun.yml: upload → gen2 function deploy, frontend UPLOAD_URL via function URL
- [x] old Cloud Run upload removed
- [x] existing backend pytest green (no import errors)

## Risks
- Cloud Functions deploy and live upload cannot be verified in this environment (no GCP access) — human must verify post-merge. New secret `CLOUD_FUNCTION_UPLOAD` must be configured in GitHub Actions before the next deploy.
- D=replace removes the working upload service; rollback is `git revert` of this PR if the function misbehaves.

## Next Action
READY_FOR_REVIEW
