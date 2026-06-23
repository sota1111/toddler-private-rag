# Worker Report

## Summary
Added a lightweight SQLite startup migration after `Base.metadata.create_all()` so existing `nursery_info` tables are patched with missing model columns. The `registration_state` column is added with `VARCHAR(20) NOT NULL DEFAULT 'registered'`, preserving existing rows as registered and allowing photo auto-read drafts to be saved.

## Changed Files
- `backend/app/migrations.py` — added idempotent SQLite schema patch helper for missing `NurseryInfo` columns.
- `backend/app/main.py` — calls the SQLite migration immediately after `create_all()` when `DATABASE_TYPE=sqlite`; Firestore remains skipped.
- `backend/tests/test_registration_state_migration.py` — regression tests for old schema draft creation and idempotent repeated migration.
- `docs/ai/60_worker_codex_report.md` — worker verification report.

## Commands Run
- `cd /workspaces/toddler-private-rag/backend && pytest tests/test_registration_state_migration.py -q` — passed: 2 passed, 4 warnings.
- `cd /workspaces/toddler-private-rag/backend && pytest -q` — passed: 98 passed, 4 warnings.
- `cd /workspaces/toddler-private-rag/backend && pytest tests/test_registration_state_migration.py -q && pytest -q` — passed: focused test 2 passed; full suite 98 passed.
- `git diff --stat main...HEAD` — no output because the fix is currently uncommitted in the working tree.
- `git diff --stat && git status --short` — working tree shows backend code/test changes plus this report; no frontend files changed.
- Frontend build was not run because no frontend files were touched.

## Acceptance Criteria
- [x] Startup SQLite migration adds missing `registration_state` column (idempotent)
- [x] Draft creation succeeds on a pre-SOT-1113 schema DB (regression test)
- [x] backend pytest passes
- [x] Firestore path untouched; change is backend-only and minimal

## Risks
The defensive migration can add missing nullable/simple model columns, but it is intentionally not a full migration framework. Future complex SQLite DDL changes should still use a proper migration path. Existing Firestore behavior is unchanged.

## Next Action
READY_FOR_REVIEW
