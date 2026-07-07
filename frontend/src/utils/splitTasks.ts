// SOT-1584: 「分割前のタスクに戻す」ボタンの表示判定。
//
// 「分割」の定義（人間コメント 2026-07-07: 「1枚の写真を複数に登録することを分割というのではなく、
// エージェントにより、(1/4)のように分割されたものを分割と呼ぶ」）に合わせて、ボタンは
// **エージェントが (1/4) のように番号付きで複数へ分割したタスク群にのみ**表示する。
// 1枚の写真から複数の独立タスクが登録されただけ（番号マーカー無し）は「分割」ではないため対象外。
//
// 判定シグナル:
//   - タイトルに `(n/N)`（分母 N≥2）の分割マーカーを持つ。マーカーは submission_agent が
//     `{書類名}({i+1}/{total})` 形式で付与する（backend/app/submission_agent.py の build_submission_task_drafts）。
//   - かつ締切グループ(deadline_group_id)に属する。マーカーだけでなくグループ所属も条件にするのは、
//     OCR 本文由来のタイトルに紛れ込む `(1/2)` 等の誤検出を避けるため（分割ステップは必ずグループを持つ）。
//
// これにより:
//   - (1/4)…(4/4) の分割ステップ群 → メンバ2件以上でボタン表示。
//   - 元タスク(アンカー, マーカー無し)・手順の無い単一提出タスク(マーカー無し) → 非該当。
//   - 1枚→複数の独立タスク / 実タスク1件 → 非該当（=ボタン非表示）。

export interface SplitTaskLike {
  source_info_id?: string | number | null;
  title?: string | null;
  deadline_group_id?: string | null;
}

// タイトル中の (n/N) 分割マーカー（分母 N≥2）を検出する。半角/全角の括弧・スラッシュを許容する。
const SPLIT_MARKER = /[（(]\s*(\d+)\s*[／/]\s*(\d+)\s*[）)]/;

/** タイトルに (n/N)（N≥2）の分割マーカーがあれば true。 */
export function hasSplitMarker(title: string | null | undefined): boolean {
  if (!title) return false;
  const m = SPLIT_MARKER.exec(String(title));
  if (!m) return false;
  const total = Number(m[2]);
  return Number.isFinite(total) && total >= 2;
}

/** エージェントが (1/N) 形式で分割したタスク群のメンバなら true。 */
export function isAgentSplitTask(item: SplitTaskLike): boolean {
  const group = item.deadline_group_id;
  if (group == null || group === '') return false;
  return hasSplitMarker(item.title);
}

/**
 * 与えたタスク群のうち、指定 source_info_id 由来の「エージェント分割タスク」の件数を数える。
 * source_info_id 未設定のタスクは対象外。
 */
export function countAgentSplitTasks(
  items: SplitTaskLike[],
  sourceInfoId: string,
): number {
  if (!sourceInfoId) return 0;
  return items.filter(
    (it) =>
      String(it.source_info_id ?? '') === sourceInfoId && isAgentSplitTask(it),
  ).length;
}
