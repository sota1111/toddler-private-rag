# Worker Report — SOT-1311 手動登録削除、登録一覧

## Fallback Disclosure (audit sink)
- 非応答ワーカー: Gemini CLI（実装）/ Codex CLI（検証）の両方
- 検出した失敗モード:
  - Gemini: `IneligibleTierError`（free-tier 廃止）→ run_gemini.sh exit 75（WORKER_NONRESPONSE）
  - Codex: usage-limit cooldown → run_codex.sh exit 75
- 対応: Worker Non-Response Fallback Policy に基づき、Claude Code が実装・検証を直接実施した。
  Quality Gate は通常どおり適用。

## Summary
手動登録機能（手動入力フォームによる登録フロー）を完全に削除した。自動登録（`/create/auto`）と
仮登録一覧（`/drafts`）、登録データ確認画面（データ一覧 `/data` → 詳細 `/data/:id`、タイトル+写真+削除）は維持。
「登録データ確認画面」は既存機能で要件を満たすため新規実装は不要だった。

## Changed Files
- `frontend/src/pages/InfoCreatePage.tsx` — 削除（手動入力フォーム）
- `frontend/src/pages/DraftConfirmPage.tsx` — 削除（手動フローの一時登録確認）
- `frontend/src/pages/RegisterConfirmPage.tsx` — 削除（手動フローの本登録確認）
- `frontend/src/contexts/CreateFlowContext.tsx` — 削除（手動フロー専用 staged-state）
- `frontend/src/contexts/createFlowContextValue.ts` — 削除
- `frontend/src/contexts/useCreateFlow.ts` — 削除
- `frontend/src/App.tsx` — 削除ページの import 撤去、CreateFlowProvider 撤去、`/create` 配下を
  `auto` のみ残し index/`*` を `/create/auto` へ redirect
- `frontend/src/components/RegisterMenu.tsx` — 「手動登録」項目を撤去（自動登録/仮登録の2項目, grid-cols-2）
- `frontend/src/i18n/messages.ts` — `nav.createManual` / `create.manualTitle`（ja/en）を撤去

## Commands Run
（下記 Codex 検証セクション参照）

## Acceptance Criteria
- [x] 手動登録機能を削除（フォーム＋確認フロー＋専用コンテキスト）
- [x] 登録データ確認画面（タイトル一覧→クリックでタイトル+写真→削除）= 既存で充足
- [x] 自動登録・仮登録は維持

## Risks
- 削除ページへの参照残りはビルドで検出されるため Quality Gate で担保。

## Next Action
READY_FOR_REVIEW
