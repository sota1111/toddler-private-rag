# Worker Report

## Summary
Issue SOT-1315「設定メニュー追加」 — Actionable: YES. Task type: IMPLEMENT (full-stack: new
frontend settings page + nav, settings persistence, and wiring the configured language into the
server-side transcription→task registration). Single cohesive feature → one PR, no decomposition.

**Fallback disclosure (audit):** Codex CLI was non-responsive for this initial task check —
`scripts/ai/run_codex.sh` exited `75` (usage-limit cooldown active until epoch 1782609660, ~17h out).
Per the Worker Non-Response Fallback Policy, Claude Code performed this read-only task check directly.

Requirement (interpreted): Add a 設定 (settings) menu/page where the user can configure (1) language,
(2) 標準時間 = timezone/standard time, (3) 子どもの名前 = child's name. After transcription, when
registering tasks, generate them in the configured language.

## Changed Files
- none (read-only check)

## Commands Run
- grep/sed across frontend/src (App.tsx nav+routes, i18n/*, components/LanguageToggle.tsx) and
  backend/app (clock.py, extraction.py, routers/attachments.py, routers/info.py)
- repo-wide search for 子ども/childName/timezone/settings/config

## Findings
- **Nav/routes:** `frontend/src/App.tsx` — bottom nav has 5 entries (dashboard/info/create/schedule/tasks,
  lines 132-142); routes at 166-190. No 設定/settings page or menu exists. Header has `LanguageToggle`
  (App.tsx:106) + `RoleToggle`.
- **Language/i18n:** `frontend/src/i18n/I18nContext.tsx` — `lang: 'ja'|'en'`, persisted in localStorage
  key `tpr.lang` (STORAGE_KEY line 5; getInitialLang 7-11; setLang writes localStorage 17-23). `t(key,vars)`
  lookup. `LanguageToggle.tsx` toggles JP/EN. So language already persists; a settings page should reuse
  `useI18n().lang/setLang`.
- **Timezone (標準時間):** only backend — `backend/app/clock.py` reads env `APP_TIMEZONE` (default
  Asia/Tokyo) for `today()`/`now_jst()`. No frontend timezone concept. A frontend timezone setting would be
  client-stored; backend clock is global env (not per-request) — wiring it into backend clock is out of
  bounded scope, so persist as a stored preference.
- **Child's name (子どもの名前):** does NOT exist anywhere (no match in frontend or backend). New concept;
  persist as a stored preference.
- **Transcription→task registration (the language requirement):**
  - Trigger: `POST /api/attachments` upload → `background_tasks.add_task(process_ocr, ..., info_id)`
    (`routers/attachments.py:220-231`).
  - `process_ocr` → `_promote_processing_draft(info_id, safe_text, structured)` (attachments.py:60-66).
  - `_promote_processing_draft` → `extraction.build_task_drafts(safe_text, dates, items)` (attachments.py:95).
  - `build_task_drafts` → `_llm_tasks(raw_text)` (extraction.py:480-530). The LLM prompt (extraction.py:487-501)
    is hard-coded Japanese and does NOT specify an output language → task title/detail come out in the
    source/Japanese. **This is where a configured `language` must be threaded** (prompt instruction
    "出力は<language>で" / "Output in English").
  - To reach the background task, the configured language must be sent on the upload request (query/form
    param) and threaded: upload → process_ocr → _promote_processing_draft → build_task_drafts → _llm_tasks.
    All have graceful fallbacks; default to 'ja' when absent (backward compatible).
- **Frontend gate:** NO `npm run typecheck` script. `frontend/package.json` scripts = `lint` (eslint),
  `build` (`tsc -b && vite build` = type gate), `e2e` (playwright via `frontend/e2e/*.spec.ts`, mocked API).
- **Backend gate:** `ruff` + `pytest` (e2e excluded by default marker).

## Acceptance Criteria
- [ ] 設定メニュー(nav)＋設定画面(/settings)が追加され、言語・標準時間(タイムゾーン)・子どもの名前を設定できる
- [ ] 設定が永続化される(localStorage、language は既存 i18n と整合)
- [ ] 文字起こし後のタスク登録が、設定した言語で生成される(upload→background task に language を伝播し _llm_tasks プロンプトに反映)
- [ ] 既存挙動の後方互換(language 未指定時は ja)
- [ ] gate: ruff0 / pytest pass / eslint0 / build0 / e2e pass

## Risks
- Backend clock APP_TIMEZONE is a global env, not per-request; the frontend timezone setting is a stored
  preference and is NOT wired to change server `today()` (avoid scope creep). State this in the report.
- Child's-name has no specified downstream effect → store + display only.
- The only hard backend behavior change is language→task registration; keep the threading minimal and
  default-safe so existing upload flow is unaffected when no language is provided.

## Next Action
READY_FOR_REVIEW
