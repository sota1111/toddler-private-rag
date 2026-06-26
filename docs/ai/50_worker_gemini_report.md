# Worker Report — SOT-1289 文字起こし中に写真追加

## Fallback Disclosure (audit sink)
- 非応答worker: Gemini CLI（`scripts/ai/run_gemini.sh` exit 75 / `WORKER_NONRESPONSE: gemini (crash exit 1)`、`IneligibleTierError: free-tier no longer supported`）。
- Codex CLI も非応答（task check / 後続検証ともに usage-limit cooldown exit 75）。
- Worker Non-Response Fallback Policy により Claude Code が実装を直接代行した。Quality Gate は通常どおり適用。

## Summary
自動登録画面（`AutoRegisterPage.tsx`）の「文字起こしを整理中」(`phase === 'enriching'`) のカードに、
「別の写真を追加」ボタンを追加。クリックで既存のファイル選択を開き、選んだ写真は既存の
`handlePhotoSelect`→確認(`confirm`)→`startUpload` の通常フローに乗る。前の写真の enrich は
バックグラウンドで継続し、新しい写真は別の draft として保存される。

並行アップロード時に、進行中だった前の `startUpload` の `finally { setPhase('done') }` 等が
新しいアップロードの画面状態を上書きする race を防ぐため、世代カウンタ `uploadSeqRef` を導入。
`startUpload` 先頭で `seq` を採番し、共有UI状態の setter（setPhase/setSavedDraft/setEnrichFailed/
setExtractError）を `applyIfCurrent`（最新世代のみ反映）でガード。サーバ保存（createInfo/
uploadAttachment/updateInfo/extractInfoDraft）はガードせず全写真分実行する。

## Changed Files
- `frontend/src/pages/AutoRegisterPage.tsx` — enriching カードに「別の写真を追加」ボタン+専用file input追加、`uploadSeqRef`世代ガード(`applyIfCurrent`)で並行アップロードのstate raceを防止
- `frontend/src/i18n/messages.ts` — `create.autoAddPhotoWhileProcessing` を ja「別の写真を追加」/ en「Add another photo」に追加

## Commands Run
- (Quality gate は Claude Code が実行: lint / build / e2e)

## Acceptance Criteria
- [x] 文字起こし整理中(enriching)に「別の写真を追加」ボタンが表示される
- [x] クリックでファイル選択→確認→追加写真の仮登録が走る
- [x] 並行アップロードで前の写真の done が新写真UIを上書きしない（uploadSeqRef ガード）
- [x] ja/en の i18n 追加

## Risks
- 確認(SOT-1288)/processing(SOT-1272)/leave-ok(SOT-1279) の既存挙動は不変。
- objectURL の生成/破棄(clearPreview / unmount useEffect)は不変。

## Next Action
READY_FOR_REVIEW
