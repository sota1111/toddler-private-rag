# Worker Report

## Summary
SOT-1052: 登録ページを「手動登録」と「自動登録（データ登録）」に分割した。

**Fallback disclosure (audit):** Gemini worker was NON-RESPONSIVE — `scripts/ai/run_gemini.sh`
exited with code 75 (worker crash: `IneligibleTierError: This client is no longer supported for
Gemini Code Assist for individuals`). This is a deterministic auth failure, so retry was not
performed (would not help). Per the Worker Non-Response Fallback Policy, Claude Code performed
this implementation directly. All Quality Gates apply unchanged and are verified by Codex.

## Changed Files
- `frontend/src/pages/InfoCreatePage.tsx` — 手動登録ページ化。写真OCR自動入力ブロックと関連state/handler/import（extractInfoDraft, compressImageFile, photoInputRef ほか）を削除。タイトルを `create.manualTitle` に変更。AI自動タグ付けと通常フォームは維持。
- `frontend/src/pages/AutoRegisterPage.tsx` — 新規。自動登録（データ登録）ページ。写真選択→圧縮→`extractInfoDraft` でOCR→`NurseryInfoCreate` を生成して `setStaged`→`/create/confirm-draft` へ遷移。失敗時はエラー表示しリトライ可。
- `frontend/src/App.tsx` — `AutoRegisterPage` import、`/create/auto` ルート追加、ナビの「登録」を「手動登録」(`/create`)＋「自動登録」(`/create/auto`) に分割。
- `frontend/src/i18n/messages.ts` — ja/en に `nav.createManual`/`nav.createAuto`/`create.manualTitle`/`create.autoTitle`/`create.autoDesc`/`create.autoExtracting`/`create.autoExtractFail` を追加。

## Commands Run
(verification delegated to Codex — see docs/ai/60_worker_codex_report.md)

## Acceptance Criteria
- [x] 手動登録ページと自動登録ページを区別（ナビ2項目＋別ルート）
- [x] 自動登録＝データ登録（写真OCRでデータ取り込み）
- [x] 既存の一時登録→確認フローを再利用

## Risks
自動登録は既存 `/api/info/extract` のOCR結果に依存。Cloud Run のOCRプロバイダ未設定時は読み取りに失敗しエラー表示となる（リトライ/手動登録へ誘導可能）。

## Next Action
READY_FOR_REVIEW
