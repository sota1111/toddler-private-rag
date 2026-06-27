# Worker Report (SOT-1317 — Claude Code fallback)

## Worker Non-Response Disclosure
- Implementation was delegated to Gemini CLI (`scripts/ai/run_gemini.sh`).
- Gemini was NON-RESPONSIVE: IneligibleTierError (UNSUPPORTED_CLIENT, free-tier discontinued) → crash, script returned exit 75.
- Codex was also NON-RESPONSIVE (usage-limit cooldown, exit 75).
- Per Worker Non-Response Fallback Policy, Claude Code performed the implementation directly.

## Summary
SOT-1317「タスク一覧表示」。ステータス絞り込みの並び順を **すべて → 確認済み → 未対応 → 対応済み** に統一し、カレンダー下のタスク一覧（SchedulePage）も同じ4値・同順に拡張した。

## Changed Files
- `frontend/src/pages/TasksPage.tsx` — `STATUS_FILTERS` を すべて→確認済み→未対応→対応済み に並べ替え（ロジック不変）。
- `frontend/src/pages/SchedulePage.tsx` — カレンダー下一覧の絞り込みを2値（all/done）→4値（all/確認済み/未対応/対応済み）に拡張。`statusFilter` 型・`STATUS_FILTERS` 追加、`listItems` を `statusFilter !== 'all'` で `ev.status===statusFilter` 絞り込みに変更（selectedDate との AND 維持）。
- `frontend/src/i18n/messages.ts` — `schedule.showConfirmed` / `schedule.showPending` を ja/en に追加。

## Commands Run
（検証は Codex 非応答のため Claude Code が直接実行。下記 Codex レポート参照）

## Acceptance Criteria
- [x] TasksPage の絞り込み順が すべて → 確認済み → 未対応 → 対応済み
- [x] カレンダー下のタスク一覧（SchedulePage）も同じ4値・同順

## Risks
- なし。backend / API は無変更。e2e S9 は名前指定で順序非依存。

## Next Action
READY_FOR_REVIEW
