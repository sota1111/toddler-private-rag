# Worker Report — SOT-1309 データ一覧クリック後の表示（タイトル+写真のみ+削除）

## Fallback Disclosure (audit sink)
- 非応答ワーカー: Gemini CLI（実装）/ Codex CLI（検証）の両方
- 検出した失敗モード:
  - Gemini: `IneligibleTierError`（free-tier 廃止, UNSUPPORTED_CLIENT）→ run_gemini.sh exit 75（crash 扱い）
  - Codex: usage-limit cooldown → run_codex.sh exit 75（CODEX_COOLDOWN_ACTIVE）
- 対応: Worker Non-Response Fallback Policy に従い、Claude Code が実装・検証を直接実施。

## Summary
データ一覧の詳細画面（`/data/:id` = `frontend/src/pages/DataDetailPage.tsx`）を、人間確定仕様
「タイトル + 写真のみ表示 + 削除可能」へ簡素化した。編集・ステータス変更・本文・持ち物・メモ・タグ・
バッジ・日付・編集フォームをすべて撤去し、表示モード専用の軽量コンポーネントに縮小した。

## Changed Files
- `frontend/src/pages/DataDetailPage.tsx` — タイトル h1 + 添付（写真）グリッド + 削除ボタン + 削除エラー表示
  のみに簡素化。編集/ステータス/本文/持ち物/メモ/タグ/バッジ/日付/編集フォーム、および不要になった
  import（updateInfo, INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES, NurseryInfoCreate）・state・mutation・
  ハンドラ（updateMutation, statusMutation, startEdit 等）を削除。delete 系（deleteInfo/deleteMutation/
  handleDelete, confirm）は保持。
- `frontend/e2e/scenarios.spec.ts` — S3 から content 可視アサート削除（タイトル可視のみ検証, テスト名調整）。
  S4（詳細での編集→保存）テストを削除（編集機能撤去のため）。S5（削除）/S8（schedule→詳細）は不変。

## Commands Run
- `npm run lint` → exit 0
- `npm run build`（tsc -b && vite build, typecheck 兼用）→ exit 0
- `npm run e2e`（playwright）→ 13 passed（S4 削除で 14→13）

## Acceptance Criteria
- [x] データ一覧の項目クリックで開く詳細画面でタイトルが表示される
- [x] 詳細画面で写真（添付画像）が表示される
- [x] 詳細画面から削除できる（confirm つき、成功で /data へ戻る）
- [x] 編集・ステータス変更は詳細画面から撤去された
- [x] lint / build / e2e すべて pass

## Risks
- 詳細画面から本文/持ち物/メモ/タグ/日付/種別/優先度/ステータスが見えなくなる（仕様どおりの意図的撤去）。
  一覧（InfoListPage）側の表示や DraftsPage の編集機能には影響しない。
- i18n キーは本ファイルでの使用を止めただけで定義は削除していない（他画面が使用中）。
- backend 無変更。merge 後の Cloud Run 再デプロイで本番反映。

## Next Action
READY_FOR_REVIEW
