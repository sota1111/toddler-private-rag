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
