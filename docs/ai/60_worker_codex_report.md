# Worker Report — Task Check (SOT-1405 reopen)

## Fallback Disclosure (Worker Non-Response Policy)
Codex CLI was NON-RESPONSIVE for this run (usage-limit cooldown; `scripts/ai/run_codex.sh`
delegated to Claude). Per the Worker Non-Response Fallback Policy, Claude Code performed the task
check directly.

## Summary
Reopen request: 「登録から選択肢の市町村を削除してください。」 — remove the "市町村" option from the
info_type registration choices (added in SOT-1403 1st run; municipality now lives in the Settings
page after SOT-1403 2nd run, so the registration option is redundant).

Issue is actionable: status In Progress, no blocking labels, requirement is clear and small (FIX,
frontend-only).

## Changed Files
- (task check only — no source files modified)

## Commands Run
- grep for "市町村" / INFO_TYPES across frontend/src

## Findings (info_type "市町村" occurrences)
- `frontend/src/pages/infoFormOptions.ts:2` — shared INFO_TYPES (registration form dropdown)
- `frontend/src/pages/InfoListPage.tsx:7` — local filter INFO_TYPES (with "すべて")
- `frontend/src/pages/SearchPage.tsx:7` — local filter INFO_TYPES (with "すべて")
- `frontend/src/i18n/messages.ts:358` (ja) / `:722` (en) — `options.infoType.市町村`

Removing "市町村" from these arrays is independent of the Settings-page municipality feature
(`tpr.municipality`, `settings.municipality` key) — those are untouched.

## Acceptance Criteria
- [x] Issue is actionable (reopen, In Progress, requirement clear)
- [x] Located all info_type "市町村" option sites (3 arrays + i18n ja/en)
- [x] Confirmed Settings-page municipality feature is independent and must remain
- [x] Confirmed removing the option is the requested change (FIX, frontend-only)

## Risks
- Existing saved records with info_type == "市町村" still display via optLabel raw-value fallback,
  so keeping vs removing the i18n keys is non-breaking. Remove the now-unused i18n keys for
  cleanliness.

## Next Action
READY_FOR_REVIEW
