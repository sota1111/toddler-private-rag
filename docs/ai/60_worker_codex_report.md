# Worker Report (SOT-1424, 2nd run — task check)

## Fallback Disclosure (audit)
- Non-responsive worker: Codex CLI.
- Detected failure mode: `scripts/ai/run_codex.sh` exited `75` (CODEX_COOLDOWN_ACTIVE —
  usage limit until epoch 1798924200). Non-response per Worker Non-Response Fallback Policy.
- Action: Claude Code performed this task check (read-only diagnosis) directly.

## Summary
SOT-1424 was reopened by the human after PR#248 (calendar-week boundary fix). New feedback:
「違う。漏れている予定がある。一部の予定は掲示板に載っているのに、一部の予定は載ってない。」
The 1st-run fix (calendar boundaries) was not the full root cause. Diagnosis confirmed:

The board's 今週の予定 / 来週の予定 sections show **only `info_type == "行事"`**, while the
今日 / 明日 sections are inclusive of any `info_type` (by `date`/`event_date`/`due_date`).
Decomposed tasks of other categories (`持ち物`/`提出物`/etc.) get an `event_date` populated
(`extraction.py:652` `event_iso = normalize_date(...)` for ANY category) but keep their
non-`行事` `info_type`. Such items appear in today/tomorrow but are dropped from the weekly /
next-week board — exactly "some schedules show, others don't."

## Evidence
- `backend/app/repository.py:253-262` (Sqlite `list_weekly`) and `:264-275` (`list_next_week`):
  filter `models.NurseryInfo.info_type == "行事"` AND `event_date` in range.
- `backend/app/repository.py:721-748` / `:750-777` (Firestore): `.where("info_type","==","行事")`
  + app-side `event_date` range filter.
- `backend/app/repository.py:231-251` (`list_today`/`list_tomorrow`): NO `info_type` restriction
  (match `date`/`event_date`/`due_date`; tomorrow also `持ち物` by `date`). → asymmetry.
- `backend/app/extraction.py:647-679` (`_task_to_draft`): `event_iso` set for any category;
  `info_type` only `行事` when category == "events".
- `frontend/src/pages/DashboardPage.tsx:171-172,212-242`: `tasksOnly` (attachments.length===0)
  applied to all four sections; legitimate decomposed week items have no attachment so this is
  not the cause, but confirms only attachment-free task records reach the board.

## Issue State
- Status: In Progress (was reopened Todo → moved to In Progress by this run).
- Labels: none. Priority: No priority. Project: toddler-private-rag.
- Latest comment: human reopen feedback (see Summary).
- Actionable: YES — single-file backend FIX in `backend/app/repository.py` (both backends),
  with a regression test in `backend/tests/test_dashboard_views.py`.

## Acceptance Criteria
- [x] Diagnosis confirmed with file:line evidence
- [x] Actionable as a focused FIX (no decomposition needed)

## Risks
- Broadening the week sections to all `info_type` may surface 持ち物/提出物 items that were
  previously hidden there — this is the intended behavior per the complaint and matches the
  inclusiveness of today/tomorrow.

## Next Action
READY_FOR_REVIEW
