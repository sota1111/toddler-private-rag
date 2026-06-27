# Worker Report (SOT-1325 task check — Claude Code fallback)

## Summary
SOT-1325「写真登録と表示」is actionable. Two requirements on the photo detail view (`/data/:id`,
`DataDetailPage.tsx`), reached by selecting an item in 写真一覧 (`RegisteredListPage`, `/registered`):

1. **写真を大きく表示** — currently the photo is shown only as a small `aspect-square object-cover`
   thumbnail inside a 2/3/4-column grid (`DataDetailPage.tsx:118-150`). Requirement: show the photo large.
2. **その下に文字起こし結果を、内容は変更せず、言語のみ設定言語で表示** — show the OCR transcription
   below the photo, content-preserving, translated into the settings language only.

## Worker Non-Response Disclosure
- Non-responsive worker: Codex CLI (`scripts/ai/run_codex.sh`).
- Failure mode: usage-limit cooldown — exited with code 75 (CODEX_COOLDOWN_ACTIVE until epoch 1782609660; now ~1782555341).
- Action: Claude Code performed this initial task check (read-only) directly per the Worker Non-Response
  Fallback Policy. Retry skipped — the cooldown is time-bounded, so a retry within the window cannot succeed.

## Findings (read-only investigation)
- actionable = **YES**.
- Photo display (a): `DataDetailPage.tsx:118-150` renders attachments as small square thumbnails; click
  opens the raw file in a new tab. Not "large".
- Transcription (b): the raw OCR transcription is stored as `Attachment.ocr_text`
  (`backend/app/models.py:39`, set via `repository.set_ocr_result`). It is **NOT currently exposed** to the
  frontend — `AttachmentResponse` (`backend/app/schemas.py:17-26`) only exposes `ocr_status`, not `ocr_text`.
  The `NurseryInfo.content` field is the LLM-restructured/categorized text (`build_structured_content`),
  i.e. "changed" — so the requirement「変更せず」points to the raw `ocr_text`, not `content`.
- "言語のみ設定言語で表示" = the raw `ocr_text` is in the photo's original language; it must be translated
  into the settings language (`useI18n().lang`, `tpr.lang`, ja|en) while preserving content. **No translate
  endpoint exists today.** A new content-preserving LLM translation is required, reusing the existing
  `ai_client.get_genai_client()` / `get_model_name()` / `default_generate_config()` / `with_retry()` pattern
  (same as `extraction.extract_titled_categories` / `_llm_tasks`). SOT-1315 precedent passes a `language`
  param from the frontend to the backend.
- Settings language source: `useI18n().lang` (I18nContext `tpr.lang`); SettingsContext holds only tz/childName.

## Change locations (file:line)
- backend/app/schemas.py:17 — add `ocr_text: Optional[str]` to `AttachmentResponse` (or a dedicated endpoint).
- backend/app/extraction.py — add `translate_text(text, language)` (content-preserving LLM translate; raw
  fallback when LLM unavailable / empty / target == source).
- backend/app/routers/attachments.py — add `GET /attachments/{att_id}/transcription?language=xx`.
- frontend/src/api/index.ts — add `getAttachmentTranscription(attId, language)`.
- frontend/src/pages/DataDetailPage.tsx — large photo display + transcription block in settings language.
- frontend/src/i18n/messages.ts — heading/loading/empty strings for the transcription section (ja/en).

## Acceptance Criteria
- [ ] 写真一覧から選択→写真を大きく表示
- [ ] その下に文字起こし結果を内容変更せず設定言語で表示

## Risks
- Interpretation: "言語のみ設定言語で表示" is read as content-preserving translation of the raw OCR text into
  the UI language. This interpretation will be disclosed in the Linear comment so the human can correct it.
- Translation cost/latency on each detail view → best-effort cache keyed by (attachment_id, language) is
  desirable but secondary to correctness.

## Recommended
- Task type: IMPLEMENT (frontend + backend). Decomposition: NOT needed — one cohesive feature, one PR.

## Quality Gate commands (this repo)
- frontend: `npm run lint`, `npm run build` (= tsc -b && vite build), `npm run e2e` (playwright)
- backend: `ruff check .`, `pytest`

## Next Action
READY_FOR_REVIEW
