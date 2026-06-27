# Worker Report

## Summary
SOT-1309 タスク確認。Codex CLI は usage-limit cooldown により非応答（exit 75）。
Worker Non-Response Fallback Policy に従い、Claude Code が read-only タスク確認を実施した。

判定: **actionable（実装可能）**。人間の最新コメント（2026-06-27 07:17）で per-task 論点は撤回され、
最終仕様は「データ一覧の項目クリックで開く詳細画面 = タイトル + 写真のみ表示 + 削除可能」に確定。
SOT-1307 への依存は解消済み。

### 詳細画面の現状（frontend/src/pages/DataDetailPage.tsx, route `/data/:id`）
現状の表示要素:
- タイトル h1（保持対象）
- 編集ボタン（撤去対象）
- 削除ボタン（保持対象, deleteMutation 既存）
- ステータス変更ドロップダウン SOT-1301（撤去対象）
- 種別/優先度/ステータスのバッジ（撤去対象）
- 日付（date/event_date/due_date）（撤去対象）
- 本文 content（撤去対象）
- 持ち物 items（撤去対象）
- メモ memo（撤去対象）
- 添付（写真画像グリッド）（保持対象 = 「写真」）
- タグ tags（撤去対象）
- 編集フォーム全体（撤去対象）

削除機能: `deleteInfo` API + `deleteMutation` + `handleDelete`（confirm つき）は既存。そのまま保持。

### 撤去/保持の整理
- 保持: backLink, タイトル h1, 添付（写真）グリッド, 削除ボタン, 削除エラー表示, loading/notFound 分岐
- 撤去: 編集ボタン, ステータス変更ドロップダウン, バッジ, 日付, content, items, memo, tags, 編集フォーム,
  および不要になる import（updateInfo, INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES, NurseryInfoCreate）と
  state/mutation（isEditing, form, saveError, statusError, updateMutation, statusMutation, startEdit 等）

### e2e への影響（frontend/e2e/scenarios.spec.ts）
- S3: 詳細で content「今月の給食は和食中心です」可視を検証 → content 撤去で**失敗する**。content アサートを除去要。
- S4: 詳細の編集→保存フロー → 編集撤去で**全体が無効**。S4 は削除する。
- S5: 詳細で削除→一覧へ戻る → 削除は保持なので**そのまま有効**。
- S8: 詳細 heading 可視 → 影響なし。

## Changed Files
- none (check only)

## Commands Run
- TARGET_REPO=/workspaces/toddler-private-rag bash scripts/ai/run_codex.sh → exit 75 (cooldown, non-response)
- read-only: DataDetailPage.tsx / e2e/scenarios.spec.ts の確認（Claude fallback）

## Acceptance Criteria
- [x] 詳細画面ファイルと表示要素を特定
- [x] 撤去/保持要素（タイトル+写真のみ+削除）を整理
- [x] 削除機能の現状を確認（deleteMutation 既存）
- [x] Verdict: actionable（per-task 依存は人間確定で解消）

## Risks
- e2e S3/S4 の更新を実装と同一PRで行わないと回帰する。
- i18n キー（records.edit/changeStatus/save 等）は DraftsPage など他画面でも使用中のため、
  本ファイルでの使用を止めるだけにしてキー定義は削除しない。

## Next Action
READY_FOR_REVIEW
