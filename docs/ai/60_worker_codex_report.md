# Worker Report — Task Check (SOT-1401)

## Fallback Disclosure (Worker Non-Response Policy)
- Non-responsive worker: **Codex CLI** (usage-limit cooldown; `scripts/ai/run_codex.sh` exited with
  non-response code `75`, cooldown until epoch 1798924200, now 1782780424). Retry futile (deterministic cooldown).
- Failure mode: usage-limit cooldown (CODEX_COOLDOWN_ACTIVE).
- Action: Claude Code performed the read-only task check directly under the Worker Non-Response Fallback Policy.

## Summary
SOT-1401 「ダイアログを表示しない機能の削除」is **actionable**. Intent: the app currently triggers
the browser-native `window.confirm()` dialog, which (on repeated firing) injects a browser checkbox
「このページでこれ以上ダイアログを生成しない / 今後このダイアログを表示しない」(prevent this page from
creating additional dialogs). The user wants that "don't show dialog" option gone — leaving only OK and
Cancel. The fix is to replace native `window.confirm()` with a custom in-app confirmation modal that has
only OK / Cancel buttons (no browser-injected suppress checkbox).

## Changed Files
- (none — investigation only)

## Commands Run
- `ls frontend/src`, `grep -rn "表示しない|ダイアログ|dialog|confirm|alert"` over `frontend/src`.
- Located all native dialog calls.

## Findings
- `window.confirm()` usages (these are where the browser injects the "don't show dialog" checkbox):
  - `frontend/src/pages/DataDetailPage.tsx:151` — `window.confirm(t('records.confirmDelete', ...))`
  - `frontend/src/pages/InfoListPage.tsx:59` — `window.confirm(t('list.confirmDelete', ...))`
  - `frontend/src/pages/DraftsPage.tsx:138` — `window.confirm(t('drafts.confirmFinalizeAll'))`
  - `frontend/src/pages/DraftsPage.tsx:154` — `window.confirm(t('drafts.confirmDiscard'))`
- No custom dialog/modal component exists yet (`frontend/src/components/` has no Dialog/Modal). All
  confirmations use the browser-native `window.confirm`. There is also `window.alert(...)` (DraftsPage)
  but that is a single-OK error notice, out of scope for the OK/Cancel requirement.
- Removal scope: introduce a reusable OK/Cancel confirm modal (component + promise-returning hook/context),
  then swap the 4 `window.confirm()` call sites to await it. No backend changes; existing i18n keys reused.
- Quality-gate commands (frontend): `npm run lint`, `npm run build` (tsc + vite), `npm run e2e`
  (Playwright). No frontend unit test suite.

## Acceptance Criteria
- [x] "don't show dialog" option located in source (browser-injected on native `window.confirm`)
- [x] removal scope identified (custom OK/Cancel modal replacing the 4 `window.confirm` call sites)
- [x] quality-gate commands identified

## Risks
- The "don't show dialog" text is browser-injected, not app code, so removing it requires moving off
  `window.confirm` to a custom modal. Custom modal must preserve current behavior (await user choice
  before delete/finalize/discard).
- Classification: **IMPLEMENT** (new reusable component + multi-file wiring) → Antigravity. No decomposition.

## Next Action
READY_FOR_REVIEW
