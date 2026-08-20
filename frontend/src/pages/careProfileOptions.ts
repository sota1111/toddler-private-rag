// SOT-2732: 個別配慮プロファイルの型付き属性の選択肢。
// 保存値は backend の正規化辞書（SOT-2730 care_normalization.py）と同じ「正規形の安定キー」を使う。
// 表示ラベルは i18n キーで解決する（careProfile.allergen.<key> / careProfile.care.<key>）。
// backend は保存値を照合時に正規化するため、正規形キーで保存しておけば往復してもチップ状態が保てる。

// アレルゲン正規形（特定原材料8品目）。care_normalization.ALLERGEN_* と一致させること。
export const ALLERGEN_KEYS = [
  'egg',
  'milk',
  'wheat',
  'buckwheat',
  'peanut',
  'shrimp',
  'crab',
  'walnut',
] as const

// 配慮カテゴリ正規形（MVP 3カテゴリ）。care_normalization.CARE_* と一致させること。
export const CARE_CATEGORY_KEYS = [
  'animal_contact',
  'loud_noise',
  'motion_sickness',
] as const

export type AllergenKey = (typeof ALLERGEN_KEYS)[number]
export type CareCategoryKey = (typeof CARE_CATEGORY_KEYS)[number]
