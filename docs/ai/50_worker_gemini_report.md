# Worker Report — SOT-1284

## Fallback Disclosure (audit sink)
Both workers were non-responsive on this run:
- Gemini CLI: crashed with `IneligibleTierError` (UNSUPPORTED_CLIENT), `run_gemini.sh` exit 75.
- Codex CLI: usage-limit cooldown, `run_codex.sh` exit 75.

Per the Worker Non-Response Fallback Policy, Claude Code performed both the implementation and the
verification (lint / build / e2e) directly.

## Summary
本登録データの詳細ページが「データが見つかりませんでした」になる不具合（SOT-1284）を修正した。
Firestore 移行（SOT-1278）以降、レコード id は文字列だが、詳細ページが `Number(params.id)` で
数値化して `NaN` になり、詳細取得クエリが `enabled: Number.isFinite(id)` で無効化されていた。
フロントの id 取り扱いを文字列対応にし、関連する id 型を `number | string` に拡張した。

## Changed Files
- `frontend/src/pages/DataDetailPage.tsx` — `Number(params.id)` を `params.id ?? ''` に変更、
  `DataDetail` の prop 型を `id: string` に、詳細クエリの `enabled` を `Boolean(id)` に変更。
- `frontend/src/types/index.ts` — `NurseryInfo.id` / `Attachment.id` / `Attachment.info_id` を
  `number | string` に拡張。
- `frontend/src/api/index.ts` — `getInfoById` / `updateInfo` / `deleteInfo` / `finalizeInfo` /
  `uploadAttachment` / `deleteAttachment` / `getAttachmentFileUrl` の id パラメータを `number | string` に拡張。
- `frontend/src/pages/DraftsPage.tsx` — 型拡張に伴い `busyId` / `editingId` state と
  `handleSaveEdit` / `handleFinalize` / `handleDiscard` を `number | string` 対応に。
- `frontend/src/pages/InfoListPage.tsx` — 型拡張に伴い `expandedId` / `deletingId` state と
  `deleteMutation.onMutate` / `handleDelete` を `number | string` 対応に。

## Commands Run
- `npm run lint` → exit 0
- `npm run build`（tsc -b + vite）→ exit 0
- `npm run e2e` → 11 passed（S3 一覧→詳細、S4 詳細編集保存、S5 詳細削除を含む）

## Acceptance Criteria
- [x] 本登録データを一覧からクリックすると詳細が表示される（id 文字列で詳細取得が走る）
- [x] 既存の数値 id 呼び出しを壊さない（型は `number | string` への拡張）
- [x] lint / build / e2e すべて pass

## Risks
- バックエンドは SOT-1282 で既に文字列 id 対応済みのため変更不要。フロントのみの修正。
- 反映には再デプロイが必要。

## Next Action
READY_FOR_REVIEW
