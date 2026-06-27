# Worker Report (SOT-1325 — Claude Code fallback)

## Worker Non-Response Disclosure
- Implementation was delegated to Gemini CLI (`scripts/ai/run_gemini.sh`).
- Gemini was NON-RESPONSIVE: IneligibleTierError (UNSUPPORTED_CLIENT, free-tier discontinued) → crash, script returned exit 75.
- Codex was also NON-RESPONSIVE (usage-limit cooldown, exit 75) for both the initial task check and any debug pass.
- Per the Worker Non-Response Fallback Policy, Claude Code performed the implementation and verification directly.

## Summary
SOT-1325「写真登録と表示」。写真一覧（/registered）→詳細（/data/:id, DataDetailPage）で、
(1) 写真を大きく表示し、(2) その下に文字起こし(OCR原文)を内容を変えず設定言語(ja/en)で表示する。

- 表示対象は LLM 再構成済みの `content` ではなく、生の文字起こし `Attachment.ocr_text`。
- 「言語のみ設定言語で表示」= 内容・構成を保ったまま言語だけ翻訳。新規 `extraction.translate_text`
  （LLM 不可/空/失敗時は原文をそのまま返す graceful fallback）を追加し、
  新規 `GET /attachments/{id}/transcription?language=ja|en` で翻訳済みテキストを返す。
- 詳細画面は小さなサムネイルのグリッドを廃止し、画像を大きく表示（`w-full h-auto max-h-[70vh] object-contain`）、
  各画像の下に文字起こしブロック（見出し/読込中/空状態）を表示。設定言語は `useI18n().lang`。

## Changed Files
- `backend/app/extraction.py` — `translate_text(text, language)` 追加（内容保持・言語のみ翻訳、graceful fallback）
- `backend/app/schemas.py` — `AttachmentTranscriptionResponse`（text/ocr_status/language）追加
- `backend/app/routers/attachments.py` — `GET /attachments/{att_id}/transcription` 追加（ocr_text を翻訳して返す）
- `backend/tests/test_attachments.py` — translate_text フォールバック + エンドポイント（翻訳/空/404/不正言語fallback）テスト追加
- `frontend/src/types/index.ts` — `AttachmentTranscription` 型追加
- `frontend/src/api/index.ts` — `getAttachmentTranscription(attId, language)` 追加
- `frontend/src/pages/DataDetailPage.tsx` — 写真の大表示 + 文字起こしブロック（子コンポーネント `AttachmentBlock`）
- `frontend/src/i18n/messages.ts` — `records.transcription` / `transcriptionLoading` / `transcriptionEmpty`（ja/en）
- `frontend/e2e/support/mockApi.ts` — seed 添付に ocr_text 付与 + `/attachments/{id}/transcription` モック
- `frontend/e2e/scenarios.spec.ts` — S11 に文字起こし表示アサート追加

## Commands Run
- backend: `ruff check`（変更ファイルはクリーン。既存テストの F401/F841 は本変更外）/ `pytest` → 135 passed
- frontend: `npm run lint` → 0 / `npm run build`(tsc -b && vite build) → 0 / `npm run e2e` → 16 passed

## Acceptance Criteria
- [x] 写真一覧から選択→写真を大きく表示
- [x] その下に文字起こし結果を内容変更せず設定言語で表示

## Risks
- 「言語のみ設定言語で表示」を内容保持の翻訳と解釈。Linear に解釈を開示済み。意図が「翻訳せず原文表示」なら
  translate_text を素通しにするだけで対応可能。
- 翻訳は表示時に LLM を呼ぶ（添付ごと・言語ごとに React Query でキャッシュ）。コスト/レイテンシが問題なら
  (attachment_id, language) キーの永続キャッシュ追加が将来の改善余地。

## Next Action
READY_FOR_REVIEW
