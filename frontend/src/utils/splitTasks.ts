// SOT-1577 REOPEN#2 / SOT-1584: 「分割前のタスクに戻す」ボタンの表示件数を、実際の分割タスクだけで
// 数えるための判定ユーティリティ。backend の extraction.is_deadline_companion と同じ規則。
//
// 写真1枚(source_info_id)からは実際の分割タスクに加え、締切調査の付随タスクにも同じ source_info_id
// が付く。付随タスクは締切グループ(deadline_group_id)に属し、submission_agent が番兵タグ
// SUBMISSION_TAG(提出書類)を必ず付ける。分割の元タスク(アンカー)は同グループでも offset 0 で
// タグを持たない。これらを分割件数から除外しないと、分割していない(=実タスク1件)のにボタンが出てしまう。
//
// SOT-1584: 基準日当日締切の付随タスク(例: 提出手順(2/2))は offset 0 のため、旧来の offset 判定だと
// 実タスクと誤カウントされてボタンが誤表示された。番兵タグを主判定に加えて offset に依存せず除外する。

// backend submission_agent.SUBMISSION_TAG と一致させること。
const SUBMISSION_TAG = '提出書類';

export interface SplitTaskLike {
  source_info_id?: string | number | null;
  tags?: string | null;
  deadline_group_id?: string | null;
  deadline_offset_days?: number | null;
}

/**
 * 締切調査の付随タスクなら true。
 * - 番兵タグ SUBMISSION_TAG を持つ（offset に依存しない主判定）。
 * - 後方互換: deadline_group_id があり offset が 0 でない。
 */
export function isDeadlineCompanion(item: SplitTaskLike): boolean {
  const tags = item.tags;
  if (tags && String(tags).includes(SUBMISSION_TAG)) return true;
  const group = item.deadline_group_id;
  if (group == null || group === '') return false;
  return (item.deadline_offset_days ?? null) !== 0;
}

/** 実際の分割タスク（付随タスクでない）なら true。 */
export function isGenuineSplitTask(item: SplitTaskLike): boolean {
  return !isDeadlineCompanion(item);
}

/**
 * 与えたタスク群のうち、指定 source_info_id 由来の“実際の分割タスク”の件数を数える。
 * 付随タスクは除外する。source_info_id 未設定のタスクは対象外。
 */
export function countGenuineSplitTasks(
  items: SplitTaskLike[],
  sourceInfoId: string,
): number {
  if (!sourceInfoId) return 0;
  return items.filter(
    (it) =>
      String(it.source_info_id ?? '') === sourceInfoId && isGenuineSplitTask(it),
  ).length;
}
