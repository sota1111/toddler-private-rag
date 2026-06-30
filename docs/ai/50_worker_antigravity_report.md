# Worker Report — SOT-1411 (4th reopen): 親タスクをアンカー化し基準日変更UIを親のみに

## Fallback Disclosure (Worker Non-Response Policy)
- Antigravity CLI: 非応答（`run_antigravity.sh` exit 75 = 認証失敗/crash）。
- Codex CLI: usage-limit cooldown（exit 75）で非応答。
- 対応: Worker Non-Response Fallback Policy に基づき、Claude Code が本実装および検証を直接実施。

## Summary
締切調査の元タスク（親）を、生成した付随タスク（子）と同じ締切グループのアンカー（基準＝offset 0）に
加え、基準日変更UIをアンカー（親）のみに表示するよう修正。これにより親の基準日変更で子タスクが一括で
ずれ、子タスク側の不要な基準日変更ボタンが消える。

## Changed Files
- `backend/app/submission_agent.py` — `assign_anchor_group(drafts, base_iso)` 追加。1回の締切調査で
  生成した全 draft を単一グループに束ね、基準日からのオフセットを再計算。base 空なら no-op で "" 返す。
- `backend/app/routers/info.py` — 手動 investigate-deadline で `assign_anchor_group` を呼び、生成後に
  元タスク（db_info）を group_id / offset 0 / base_date でアンカー更新。
- `backend/app/routers/attachments.py` — 自動締切調査経路でも同様に元タスク（cid）をアンカー更新。
- `frontend/src/pages/DataDetailPage.tsx` — 基準日変更UIの表示条件を
  `deadline_group_id && deadline_offset_days === 0`（アンカー＝親のみ）に変更。子タスクには非表示。
- `backend/tests/test_investigate_deadline.py` — 親アンカー化／基準日空時の非アンカーの回帰テスト追加。
- `backend/tests/test_submission_agent.py` — `assign_anchor_group` の単体テスト追加。
- `backend/tests/test_attachments.py` — 自動経路の回帰テストを新アンカーモデルに更新（親アンカー検証追加）。

## Commands Run
- `ruff check app` → All checks passed
- `pytest` → 243 passed, 1 skipped
- `npm run lint` → 0
- `npm run build` → 0 (tsc + vite)
- `npm run e2e` → 17 passed

## Acceptance Criteria
- [x] 元タスク(親)が締切グループのアンカー(offset 0)になる（手動・自動の両経路）
- [x] 基準日変更UIはアンカー(親)のみに表示、子タスクには非表示
- [x] 親の基準日変更で子タスクが一括でずれる（既存 reschedule ハンドラがグループ全件を offset で再計算）
- [x] 基準日が空のときはグループ化・ボタン表示なし
- [x] backend ruff 0 / pytest pass / frontend lint 0 / build 0 / e2e 17

## Risks
- 本修正前に生成済みの締切調査タスクは旧モデル（親がグループ外）のため、親アンカーUIは出ない。
  締切調査をやり直す（写真再登録 or 締め切り調査ボタン）と新モデルで再生成される。
- 親には基準日変更UIに加え通常の日付編集（SOT-1415）も残る。連動は基準日変更UI経由が対象。

## Next Action
READY_FOR_REVIEW
