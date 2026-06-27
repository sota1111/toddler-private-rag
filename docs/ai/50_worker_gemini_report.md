# Worker Report — SOT-1314 (Claude fallback)

## Summary
SOT-1314「タスク一覧機能追加」。Gemini CLI は非応答（`scripts/ai/run_gemini.sh` exit 75 =
IneligibleTierError / UNSUPPORTED_CLIENT, free-tier 廃止）のため、Worker Non-Response Fallback
Policy に基づき Claude Code が実装を直接実施。

- 非応答ワーカー: Gemini CLI
- 検出した失敗モード: IneligibleTierError（exit 1 → run script が exit 75 で WORKER_NONRESPONSE 化）
- 対応: Claude Code が直接実装

TasksPage の表示切替を 2 値（すべて/対応済み）→ 4 値ステータス絞り込み
（すべて/未対応/対応済み/確認済み）に拡張。Issue 本文の「未確認」はアプリに存在しない値のため、
実在ステータス3種+すべて を採用（Linear で開示済み）。

## Changed Files
- `frontend/src/pages/TasksPage.tsx` — statusFilter を `'all'|'未対応'|'対応済み'|'確認済み'` に拡張。
  STATUS_FILTERS マップ（状態キー→i18nラベルキー）でボタン描画。絞り込みは `'all'` で全件、
  それ以外は `item.status === statusFilter`。日付つき・event_date昇順は維持。
- `frontend/src/i18n/messages.ts` — `tasks.showPending`(未対応/Pending), `tasks.showConfirmed`
  (確認済み/Confirmed) を ja/en に追加（showAll/showDone は流用）。
- `frontend/e2e/scenarios.spec.ts` — S9 に絞り込みアサート追加（確認済みで運動会(未対応)が消え、
  未対応で再表示）。

## Commands Run
- 実装のみ（検証は Codex 役の Claude fallback で別途実施）。

## Acceptance Criteria
- [x] すべて/未対応/対応済み/確認済み でタスク一覧を絞り込める
- [x] 既定は「すべて」で全件表示（S5/S9 維持）
- [x] i18n ja/en 両対応・ラベルは i18n から取得（直書きなし）

## Risks
- ラベル相違（Issue「未確認」 vs 実在「確認済み」）は Linear コメントで開示済み。
- TasksPage は unit test 無し。ゲートは lint / build / e2e。

## Next Action
READY_FOR_REVIEW
