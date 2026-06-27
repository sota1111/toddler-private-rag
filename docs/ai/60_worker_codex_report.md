# Worker Report

## Summary
SOT-1311 タスク確認。Codex CLI は usage-limit cooldown により非応答（exit 75）。
Worker Non-Response Fallback Policy に従い、Claude Code が read-only タスク確認を実施した。

判定: **actionable（実装可能）**。要件は2点:
1. 手動登録機能を削除する。
2. 登録データ確認画面（写真タイトル一覧→クリックでタイトル+写真表示→削除）を用意する。

要件2の「登録データ確認画面」は **既に存在する**（DataListPage→DataDetailPage, SOT-1217/1309）。
よって本Issueの実体は **要件1（手動登録の撤去）** が中心。

### 手動登録フロー（撤去対象, frontend）
手動登録は以下の3ページ＋専用コンテキストで構成され、自動登録（/create/auto）とは独立:
- `frontend/src/pages/InfoCreatePage.tsx` — 手動入力フォーム, route `/create` index, `create.manualTitle`
- `frontend/src/pages/DraftConfirmPage.tsx` — 手動フローの一時登録確認, route `/create/confirm-draft`
- `frontend/src/pages/RegisterConfirmPage.tsx` — 手動フローの本登録確認, route `/create/confirm-register`
- `frontend/src/contexts/CreateFlowContext.tsx` / `createFlowContextValue.ts` / `useCreateFlow.ts`
  — 上記3ページのみが使用（`useCreateFlow` 利用箇所: App.tsx + 上記3ページのみ。AutoRegisterPage は不使用）
- `frontend/src/App.tsx` — imports(InfoCreatePage/DraftConfirmPage/RegisterConfirmPage),
  CreateFlowProvider ラッパ, `/create` 配下のルート定義（index/confirm-draft/confirm-register）
- `frontend/src/components/RegisterMenu.tsx:43-53` — 「手動登録」項目（to `/create`, `nav.createManual`）
- `frontend/src/i18n/messages.ts` — `nav.createManual`(L15/L293), `create.manualTitle`(L139/L417)

### 自動登録・仮登録は保持
- `/create/auto` = AutoRegisterPage（CreateFlow 不使用・独立, ナビ「登録」の遷移先）→ 保持
- `/drafts` = DraftsPage（仮登録一覧）→ 保持
- `/create` index は手動撤去後 `/create/auto` へ redirect する

### 登録データ確認画面（要件2）の現状 = 既存で要件を満たす
- `DataListPage.tsx`（route `/data`, ナビ`nav.records`）= タイトルのみ一覧 → クリックで `/data/:id` 遷移
- `DataDetailPage.tsx`（route `/data/:id`）= タイトル h1 + 写真グリッド + 削除（SOT-1309 で簡素化済）
- 新規作成は不要。要件を満たすため確認のみ。

### e2e への影響（frontend/e2e/）
- e2e は `/create/auto`（保持）への遷移のみ参照。手動 `/create` index / RegisterMenu の手動項目は
  e2e で直接テストされていない（smoke.spec.ts / scenarios.spec.ts とも `a[href="/create/auto"]` を使用）。
  → 手動登録撤去による e2e 回帰リスクは低い。

## Changed Files
- none (check only)

## Commands Run
- TARGET_REPO=/workspaces/toddler-private-rag bash scripts/ai/run_codex.sh → exit 75 (cooldown, non-response)
- read-only: App.tsx / RegisterMenu.tsx / InfoCreatePage.tsx / DraftConfirmPage.tsx / DataListPage.tsx /
  messages.ts / e2e/*.ts の確認（Claude fallback）

## Acceptance Criteria
- [x] 手動登録の構成ファイルを特定（line番号つき）
- [x] 登録データ確認画面（list+detail+delete）の現状を確認（既存で要件充足）
- [x] auto/drafts を壊さず手動登録を撤去する変更点を列挙
- [x] Verdict: actionable

## Risks
- DraftConfirmPage/RegisterConfirmPage/CreateFlow は手動フロー専用のため削除可だが、削除漏れ
  （App.tsx のルート/Provider）があるとビルドエラーになる → 同一PRで一括撤去する。
- i18n の `create.field*` 等は手動フローページが使っていたが共有定義。未使用化しても害はないので
  キー定義の削除は最小限（manual 固有の nav.createManual / create.manualTitle のみ）にとどめる。

## Next Action
READY_FOR_REVIEW
