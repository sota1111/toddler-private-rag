# Worker Report — SOT-1405 (reopen): 登録の選択肢から市町村を削除

## Fallback Disclosure (Worker Non-Response Policy)
- Codex CLI was NON-RESPONSIVE (usage-limit cooldown; run_codex.sh delegated to Claude).
- Antigravity CLI was NON-RESPONSIVE (`authentication failed or timed out`; WORKER_NONRESPONSE exit).
- Per the Worker Non-Response Fallback Policy, Claude Code performed the implementation AND the
  verification directly. All Quality Gates were applied identically.

## Summary
Removed the redundant info_type option "市町村" from the registration form dropdown and the two
filter dropdowns, and removed the now-unused i18n keys. The municipality is managed on the Settings
page (SOT-1403), so this option is no longer needed.

## Changed Files
- `frontend/src/pages/infoFormOptions.ts` — remove "市町村" from shared INFO_TYPES (registration form)
- `frontend/src/pages/InfoListPage.tsx` — remove "市町村" from filter INFO_TYPES
- `frontend/src/pages/SearchPage.tsx` — remove "市町村" from filter INFO_TYPES
- `frontend/src/i18n/messages.ts` — remove `options.infoType.市町村` (ja + en)

## Commands Run
- `npm run lint` → exit 0
- `npm run build` (tsc + vite) → exit 0
- `npm run e2e` → 17 passed

## Acceptance Criteria
- [x] 登録の選択肢から「市町村」が削除されている
- [x] フィルタ（一覧・検索）の選択肢からも「市町村」が削除されている
- [x] 設定画面の市町村機能（SOT-1403）は無変更
- [x] Lint / Build(TypeCheck) / E2E すべて pass

## Risks
- 既存に info_type=="市町村" の保存データがある場合、optLabel の raw 値 fallback で表示は維持される
  （i18n キー削除は非破壊）。

## Next Action
READY_FOR_REVIEW
