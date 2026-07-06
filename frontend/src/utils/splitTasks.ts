// SOT-1577 REOPEN#2: 「分割前のタスクに戻す」ボタンの表示件数を、実際の分割タスクだけで数えるための
// 判定ユーティリティ。backend の extraction.is_deadline_companion と同じ規則。
//
// 写真1枚(source_info_id)からは実際の分割タスクに加え、締切調査の付随タスクにも同じ source_info_id
// が付く。付随タスクは締切グループ(deadline_group_id)に属し offset(≠0)を持つ。これらを分割件数から
// 除外しないと、分割していない(=実タスク1件)のにボタンが出てしまう。

export interface SplitTaskLike {
  source_info_id?: string | number | null;
  deadline_group_id?: string | null;
  deadline_offset_days?: number | null;
}

/** 締切調査の付随タスク（deadline_group_id があり offset が 0 でない）なら true。 */
export function isDeadlineCompanion(item: SplitTaskLike): boolean {
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
