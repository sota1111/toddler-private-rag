// 登録フォームの選択肢（保存値は日本語のまま）。複数ページで共有するため .ts に分離。
export const INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"]
// SOT-1355: ステータスを3つに統一（未確認 → 未対応 → 対応済）。`確認済` は選択肢から削除。
// 旧表記/旧値（確認済/確認済み/対応済み）で保存済みの既存データは i18n 旧キー残置 +
// 配色 switch の case 残置 + backend 後方互換で表示のみ扱う。
export const STATUS_TYPES = ["未確認", "未対応", "対応済"]
export const PRIORITY_TYPES = ["高", "普通", "低"]

// SOT-1345: 一覧の日付チップをステータス色で表示するための共有ヘルパ。
// 配色は InfoListPage の getStatusColor と統一。旧値（確認済/確認済み/対応済み）も後方互換で同色。
// Tailwind の動的クラス生成を避けるため、完全な静的クラス文字列を返す。
export const getStatusDateChipClass = (status?: string): string => {
  switch (status) {
    case "未確認":
      return "bg-orange-100 text-orange-800";
    case "未対応":
      return "bg-yellow-100 text-yellow-800";
    case "対応済":
    case "対応済み":
      return "bg-green-100 text-green-800";
    case "確認済":
    case "確認済み":
      return "bg-brand-soft text-brand-strong";
    default:
      return "bg-surface-muted text-foreground";
  }
};

// SOT-1370: 一覧上部のステータス絞り込みピルの配色を、日付チップ(getStatusDateChipClass)の
// ステータス色分け（未確認=orange / 未対応=yellow / 対応済=green）に合わせるためのヘルパ。
// 選択中(active)は ring + 濃いめの背景/境界で強調する。'all'（すべて）はブランド色のまま。
// Tailwind の動的クラス生成を避けるため、完全な静的クラス文字列を返す。
export const getStatusFilterPillClass = (
  status: "all" | "未確認" | "未対応" | "対応済",
  active: boolean,
): string => {
  switch (status) {
    case "未確認":
      return active
        ? "bg-orange-200 text-orange-900 border-orange-400 ring-2 ring-orange-300"
        : "bg-orange-100 text-orange-800 border-orange-200 hover:bg-orange-200";
    case "未対応":
      return active
        ? "bg-yellow-200 text-yellow-900 border-yellow-400 ring-2 ring-yellow-300"
        : "bg-yellow-100 text-yellow-800 border-yellow-200 hover:bg-yellow-200";
    case "対応済":
      return active
        ? "bg-green-200 text-green-900 border-green-400 ring-2 ring-green-300"
        : "bg-green-100 text-green-800 border-green-200 hover:bg-green-200";
    case "all":
    default:
      return active
        ? "bg-brand text-white border-brand"
        : "bg-surface text-foreground border-border hover:bg-surface-muted";
  }
};

// SOT-1368 follow-up: 子どもごとに色を割り当てる共有ヘルパ。
// children 配列内の登録順（インデックス）でパレットを決定的に割り当て、
// 一覧の子ども名タグ（chip）とカレンダーの日付強調ドット（dot）で同じ色を使い対応づける。
// ステータス色（orange/yellow/green = getStatusDateChipClass）と衝突しない色相のみ採用する。
// Tailwind の動的クラス生成を避けるため、完全な静的クラス文字列を返す。
export interface ChildColorClasses {
  chip: string;
  dot: string;
}

const CHILD_COLOR_PALETTE: ChildColorClasses[] = [
  { chip: "bg-sky-100 text-sky-800", dot: "bg-sky-500" },
  { chip: "bg-pink-100 text-pink-800", dot: "bg-pink-500" },
  { chip: "bg-violet-100 text-violet-800", dot: "bg-violet-500" },
  { chip: "bg-fuchsia-100 text-fuchsia-800", dot: "bg-fuchsia-500" },
  { chip: "bg-teal-100 text-teal-800", dot: "bg-teal-500" },
  { chip: "bg-rose-100 text-rose-800", dot: "bg-rose-500" },
  { chip: "bg-indigo-100 text-indigo-800", dot: "bg-indigo-500" },
  { chip: "bg-cyan-100 text-cyan-800", dot: "bg-cyan-500" },
];

// 子ども未指定/未解決（children 未取得・不明な child_id）時の中立色。
// SOT-1384: カレンダーの予定日マークを PC でもはっきり視認できるよう、
// 既定ドットを淡い bg-accent（amber）から高コントラストな bg-brand（orange）に変更する。
const NEUTRAL_CHILD_COLOR: ChildColorClasses = {
  chip: "bg-surface-muted text-foreground",
  dot: "bg-brand",
};

export const getChildColorClasses = (
  childId: string | null | undefined,
  children: { id: number | string; name: string }[],
): ChildColorClasses => {
  if (!childId) return NEUTRAL_CHILD_COLOR;
  const index = children.findIndex((c) => String(c.id) === String(childId));
  if (index < 0) return NEUTRAL_CHILD_COLOR;
  return CHILD_COLOR_PALETTE[index % CHILD_COLOR_PALETTE.length];
};
