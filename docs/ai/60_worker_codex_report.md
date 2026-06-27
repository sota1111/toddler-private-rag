# Worker Report (SOT-1317 — Claude Code fallback)

## Worker Non-Response Disclosure
- Task check was delegated to Codex CLI (`scripts/ai/run_codex.sh`).
- Codex was NON-RESPONSIVE: usage-limit cooldown active → script returned exit 75 (CODEX_COOLDOWN_ACTIVE, ~16h out).
- Per Worker Non-Response Fallback Policy, Claude Code performed the read-only task check directly.

## Summary
SOT-1317「タスク一覧表示」のタスクチェック。Issue は actionable。要求は「ステータス絞り込みの並び順を すべて → 確認済み → 未対応 → 対応済み にし、カレンダー下のタスク一覧も同様にする」。

- `frontend/src/pages/TasksPage.tsx:22-27` — 現状 `STATUS_FILTERS` の並びは [すべて, 未対応, 対応済み, 確認済み]。要求順 [すべて, 確認済み, 未対応, 対応済み] に並べ替える。
- `frontend/src/pages/SchedulePage.tsx:33,76-77,209-229` — カレンダー下の一覧は 2値（すべて / 対応済み）のみ。TasksPage と同様の4値・同順に拡張する必要あり。
- `frontend/src/i18n/messages.ts:39-40,340-341` — `schedule.showPending` / `schedule.showConfirmed` が未定義。追加が必要（`tasks.*` 側は4種揃っている）。
- e2e `frontend/e2e/scenarios.spec.ts:155-157` は `getByRole('button', { name: '確認済み' })` 等の名前指定で順序非依存 → 並べ替えで破綻しない。

実在ステータスは 未対応 / 対応済み / 確認済み の3種（SOT-1314）。Issue 本文の語はすべて実在ステータスに対応。

## Changed Files
- none (task check only)

## Commands Run
- grep STATUS_FILTERS / statusFilter / 未対応 / 対応済み / 確認済み（TasksPage, SchedulePage, messages.ts, e2e）

## Acceptance Criteria
- [ ] TasksPage の絞り込み順が すべて → 確認済み → 未対応 → 対応済み
- [ ] カレンダー下のタスク一覧（SchedulePage）も同じ4値・同順

## Risks
- SchedulePage は日付選択フィルタ（selectedDate）と併存。statusFilter 拡張時に selectedDate との AND が崩れないようにする。

## Next Action
READY_FOR_REVIEW
