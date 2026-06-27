# Worker Report

## Summary
Actionable: YES. Task type: IMPLEMENT (multi-file removal + e2e rework, single PR, no decomposition).

**Fallback disclosure (audit):** Codex CLI was non-responsive for this initial task check — `scripts/ai/run_codex.sh` exited `75` (usage-limit cooldown active until epoch 1782609660). Per the Worker Non-Response Fallback Policy, Claude Code performed this read-only task check directly.

"データ画面" = the registered-data **list** page `DataListPage` at route `/data`, surfaced by the bottom-nav menu entry labeled "データ" (`nav.records`). This is what must be removed from the menu and as a feature.

**CRITICAL constraint:** the *detail* page `DataDetailPage` at `/data/:id` is a SHARED view navigated to from 4 other features and MUST be kept:
- `frontend/src/pages/AskPage.tsx:161` → `/data/${s.info_id}` (RAG source link, SOT-1276)
- `frontend/src/pages/DashboardPage.tsx:44` → `/data/${item.id}` (board item link, SOT-1281)
- `frontend/src/pages/SchedulePage.tsx:246` → `/data/${item.id}` (calendar list link)
- `frontend/src/pages/TasksPage.tsx:79` → `/data/${item.id}` (tasks list link, SOT-1313)

So scope = remove the **list** page + its menu entry only; keep the **detail** route/component.

## Changed Files
- none (read-only check)

## Commands Run
- grep for `/data`, `data`, `records`, `データ` across frontend/src, frontend/e2e
- read App.tsx nav/routes, DataListPage.tsx, DataDetailPage.tsx, i18n/messages.ts

## Findings
- Menu entry: `frontend/src/App.tsx:138-145` NavLink `to="/data"` (label `nav.records`, `DataIcon`).
- DataIcon definition: `frontend/src/App.tsx:48-50` (used only by this NavLink).
- Routes: `App.tsx:181` `/data` → DataListPage (REMOVE); `App.tsx:182` `/data/:id` → DataDetailPage (KEEP).
- Import: `App.tsx:18` DataListPage (REMOVE); `App.tsx:19` DataDetailPage (KEEP).
- Page component: `frontend/src/pages/DataListPage.tsx` (REMOVE whole file). Uses shared `getInfoList` API (no dedicated backend; KEEP backend `/info/`).
- i18n exclusive to the list page: `nav.records`, `records.title`, `records.empty` (ja: messages.ts:17,128,129; en: 301,412,413). REMOVE these 3 keys × 2 langs.
- i18n KEPT (used by DataDetailPage): `records.back/edit/save/cancel/delete/deleting/confirmDelete/deleteError/saveError/changeStatus/statusError/notFound/attachmentsHeading`.
- Dangling back-nav after removal: `DataDetailPage.tsx:30` `navigate('/data')` (post-delete) and `:44` `<Link to="/data">` back-link both point to the removed list route. Must redirect to browser back (`navigate(-1)`) since the detail page is now reached from other pages.
- e2e referencing the list/menu (must be reworked/removed): `frontend/e2e/scenarios.spec.ts` S1 (line 8-10 unauth /data→/login), S2 (22-23 nav click→/data list), S3 (33-44 list→detail), S4 (55-61 detail→back to /data list); `frontend/e2e/smoke.spec.ts:60` `goto('/data')`. Scenarios at lines 134/155 navigate to `/data/2` from Schedule/Tasks lists and KEEP working (detail route retained).

## Acceptance Criteria
- [x] データ画面がメニューから削除できる (remove NavLink + route + DataListPage)
- [x] データ画面の機能（ページ/route）が削除できる (delete DataListPage.tsx, /data route, DataIcon, list i18n keys)
- [x] 他画面の /data 依存が洗い出されている (4 inbound /data/:id links → keep detail page)
- [x] Verdict: actionable

## Risks
- Do NOT delete DataDetailPage or `/data/:id` route — breaks Ask/Dashboard/Schedule/Tasks navigation.
- DataDetailPage back navigation must be re-pointed away from `/data` (use `navigate(-1)`), else dead link.
- e2e S1-S4 + smoke must be updated; keep detail-route scenarios reachable via Schedule/Tasks menus.

## Next Action
READY_FOR_REVIEW
