# Worker Report — SOT-1276

## Summary
質問への回答の「出典」をクリックするとデータ一覧の該当資料 (`/data/:id`) へ遷移できるようにした。

Implementation performed by Claude Code under the Worker Non-Response Fallback Policy:
`scripts/ai/run_gemini.sh` exited 75 (IneligibleTierError / UNSUPPORTED_CLIENT — Gemini CLI free-tier
no longer supported). Gemini was non-responsive, and Codex was also in cooldown (exit 75 earlier), so
Claude Code did this small single-file FIX directly.

## Changed Files
- `frontend/src/pages/AskPage.tsx` — import `Link` from react-router-dom; in the sources list, render
  the document label as `<Link to={`/data/${s.info_id}`}>` when `s.info_id` is present (not null / not
  empty string), otherwise keep the plain `<span>`. Brand-colored, `hover:underline`, `truncate` layout
  preserved. Badge / score / snippet unchanged.

## Commands Run
- (verification in Codex/Claude step — see docs/ai/60_worker_codex_report.md)

## Acceptance Criteria
- [x] Clicking a source with info_id navigates to `/data/<info_id>`
- [x] Sources without info_id stay plain text (no broken `/data/null` link)
- [x] No change to badge / relevance score / snippet / ask flow

## Risks
- None significant. `info_id` already provided by backend; route `/data/:id` already exists.

## Next Action
READY_FOR_REVIEW
