import type { MenuDay } from '../types';
import { ALLERGEN_KEYS, type AllergenKey } from '../pages/careProfileOptions';

// SOT-2746: 献立カレンダーの「アレルギー注意」表示用。
// その日の献立（給食・おやつ・主要食材）の文字列を走査し、特定原材料8品目の
// アレルゲンが「含まれる可能性」をヒューリスティックに検出する。
// 判定は表記から推定するだけで断定はしない（backend care_normalization の別名辞書に準拠）。
// 個別配慮プロファイルに登録済みのアレルゲンと突き合わせ、一致した日をカレンダーで警告する。

// 各アレルゲンの検出語（backend care_normalization._ALLERGEN_ALIASES を土台に、献立の
// 料理名で現れやすい加工品名を補ったもの）。過検出より取りこぼし低減を優先しつつ、
// 「乳」単体（豆乳/乳酸で誤検出）など曖昧語は避ける。
const ALLERGEN_TERMS: Record<AllergenKey, string[]> = {
  egg: ['卵', 'たまご', 'タマゴ', '玉子', '鶏卵', 'エッグ', 'マヨネーズ', 'オムレツ', '茶碗蒸し'],
  milk: [
    '牛乳', '乳製品', '乳成分', 'スキムミルク', 'ミルク', 'チーズ', 'バター',
    '生クリーム', 'ヨーグルト', '練乳', 'グラタン', 'シチュー',
  ],
  wheat: [
    '小麦', 'こむぎ', 'パン', 'うどん', 'そうめん', 'ラーメン', '中華麺', 'マカロニ',
    'スパゲ', 'パスタ', '餃子', 'シュウマイ', '焼売', '天ぷら', 'フライ', 'から揚げ',
    '唐揚げ', 'お好み焼き', 'ホットケーキ', 'クッキー', 'ケーキ', '麩',
  ],
  buckwheat: ['そば', '蕎麦', 'ソバ'],
  peanut: ['落花生', 'ピーナッツ', 'ピーナツ', '南京豆'],
  shrimp: ['えび', 'エビ', '海老'],
  crab: ['かに', 'カニ', '蟹'],
  walnut: ['くるみ', 'クルミ', '胡桃'],
};

// その日の献立から、テキストとして検出できたアレルゲンキーを返す（8品目の並び順）。
export function detectMenuAllergens(day: MenuDay): AllergenKey[] {
  const mi = day.main_ingredients;
  const texts: string[] = [
    ...(day.lunch ?? []),
    ...(day.morning_snack ?? []),
    ...(day.afternoon_snack ?? []),
    ...(mi?.red ?? []),
    ...(mi?.yellow ?? []),
    ...(mi?.green ?? []),
    ...(mi?.other ?? []),
  ];
  const haystack = texts.join(' ');
  return ALLERGEN_KEYS.filter((key) =>
    ALLERGEN_TERMS[key].some((term) => haystack.includes(term)),
  );
}

// 検出アレルゲンのうち、登録済みプロファイルのアレルゲンと一致するものだけを返す（警告対象）。
export function matchedAllergens(
  detected: AllergenKey[],
  profileAllergens: ReadonlySet<string>,
): AllergenKey[] {
  return detected.filter((key) => profileAllergens.has(key));
}
