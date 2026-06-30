# Worker Report — SOT-1401 ダイアログを表示しない機能の削除

## Fallback Disclosure (Worker Non-Response Policy)
- Non-responsive worker: **Antigravity CLI** — `scripts/ai/run_antigravity.sh` required interactive
  OAuth re-authentication and timed out, exiting with non-response code `75`
  (`WORKER_NONRESPONSE: antigravity (invalid report (missing ## Next Action))`).
- Codex CLI was also non-responsive earlier (usage-limit cooldown, exit `75`).
- Per the Worker Non-Response Fallback Policy, Claude Code performed the implementation (Antigravity's
  role) and verification (Codex's role) directly. All Quality Gates applied unchanged.

## Summary
Replaced the browser-native `window.confirm()` confirmations with a custom in-app confirmation modal
that offers ONLY OK and Cancel. Native `confirm()` dialogs caused the browser to inject a "don't show
this dialog again / このページでこれ以上ダイアログを生成しない" checkbox on repeated firing — that
"don't show dialog" option is what SOT-1401 wanted removed. The custom modal has no such option.

## Changed Files
- `frontend/src/components/confirmDialogContext.ts` — NEW. `ConfirmContext` + `useConfirm()` hook +
  `ConfirmFn` type (split out from the component file to satisfy `react-refresh/only-export-components`,
  mirroring the existing i18n `i18nContextValue.ts` pattern).
- `frontend/src/components/ConfirmDialog.tsx` — NEW. `ConfirmDialogProvider`: renders a single modal
  overlay (`role="dialog"`, `aria-modal`) with OK (resolves true) / Cancel (resolves false). Promise-based;
  Cancel / overlay click resolves false. Uses existing Tailwind tokens (`bg-surface`, `bg-brand`,
  `hover:bg-brand-strong`, `border-border`).
- `frontend/src/App.tsx` — mount `ConfirmDialogProvider` inside `<I18nProvider>` (so it has translations),
  wrapping the rest of the provider stack.
- `frontend/src/i18n/messages.ts` — added `common.ok` / `common.cancel` to both `ja` ('OK'/'キャンセル')
  and `en` ('OK'/'Cancel') blocks.
- `frontend/src/pages/DataDetailPage.tsx` — `handleDelete` now `await confirm(...)` instead of `window.confirm`.
- `frontend/src/pages/InfoListPage.tsx` — `handleDelete` now async, `await confirm(...)`.
- `frontend/src/pages/DraftsPage.tsx` — `handleFinalizeAll` / `handleDiscard` now `await confirm(...)`.
- `frontend/e2e/scenarios.spec.ts` — S5 (delete) and S12 (finalize-all) updated: removed
  `page.on('dialog', d => d.accept())` and instead click the modal's `OK` button. (`window.alert` error
  notices in DraftsPage left untouched — out of scope.)

## Commands Run
- `npm run lint` → 0 errors (after splitting context/hook into a separate module + dropping a
  ref-during-render).
- `npm run build` (tsc -b && vite build) → success, 162 modules.
- `npx playwright test` → 17 passed.
- `grep -rn "window.confirm" frontend/src` → none (only a comment reference remains).

## Acceptance Criteria
- [x] No browser "don't show dialog" option — native `window.confirm` removed app-wide.
- [x] Confirmations show only OK and Cancel (custom modal).
- [x] Destructive actions still gated on user confirmation (behavior preserved).
- [x] lint + build + e2e pass.

## Risks
- The "don't show dialog" text was browser-injected, not app code; the only reliable removal is moving
  off `window.confirm` to a custom modal (done).
- `window.alert(...)` error notices in DraftsPage remain native (single-OK, out of scope for an OK/Cancel
  requirement). Can be migrated later if desired.

## Next Action
READY_FOR_REVIEW
