import type { MenuDay } from '../types';

// menu-calendar: 献立カレンダーのセル表示用。給食の「主菜のたんぱく源」を
// 「体をつくる（赤）」列(main_ingredients.red)から選び、肉/魚/豆に分類してアイコン化する。
// スマホではセルにアイコン＋数文字しか出ないため、料理名ではなく主菜のたんぱく源
// (豚もも・ししゃも・豆腐 等)を出す。牛乳やだし・海藻など主菜でないものはスキップする。

export type ProteinCategory = '肉' | '魚' | '豆';

// 主菜のたんぱく源ではない（＝スキップする）もの: 乳・海藻・だし・寒天など。
const SKIP = [
  '牛乳', 'スキムミルク', 'ミルク', 'わかめ', '昆布', 'あおのり', 'のり',
  'ひじき', '寒天', 'かつお節', 'だし',
];
// 判定は 魚 → 肉 → 豆 の順（「魚肉」等の取り違えを避けるため魚を先に見る）。
const FISH = [
  'さけ', '鮭', 'たら', 'かれい', 'ししゃも', 'ほき', 'ホキ', '白身魚', 'ぶり',
  'あじ', 'さば', 'いわし', 'えび', 'ちりめん', 'じゃこ', 'しらす', 'かつお',
  'まぐろ', 'ツナ', 'たい', 'ほたて', 'ホタテ', 'あさり', '貝', 'いか', 'たこ',
];
const MEAT = [
  '豚', '鶏', '牛肉', 'ひき肉', '肉', 'ささ', 'レバー', 'ハム', 'ベーコン',
  'ウインナー', 'ソーセージ', '卵',
];
const BEAN = [
  '豆腐', '高野豆腐', '油あげ', '油揚げ', '厚揚げ', '大豆', '納豆', 'きな粉',
  '豆乳', 'おから', 'あん', '粉豆腐', '枝豆', 'あずき', 'がんも',
];

const ICON: Record<ProteinCategory, string> = { '肉': '🍖', '魚': '🐟', '豆': '🫘' };

function classifyItem(item: string): ProteinCategory | null {
  if (SKIP.some((k) => item.includes(k))) return null;
  if (FISH.some((k) => item.includes(k))) return '魚';
  if (MEAT.some((k) => item.includes(k))) return '肉';
  if (BEAN.some((k) => item.includes(k))) return '豆';
  return null;
}

export interface MenuProtein {
  icon: string;
  label: string;
  category: ProteinCategory | null;
}

// 給食のたんぱく源を1つ選ぶ: 赤列を順に見て、最初に肉/魚/豆へ分類できたものを主菜とする。
// 分類できるものが無ければ、赤列先頭 or 給食1品目にフォールバック（汎用アイコン🍚）。
export function pickMenuProtein(day: MenuDay): MenuProtein {
  const reds = day.main_ingredients?.red ?? [];
  for (const item of reds) {
    const category = classifyItem(item);
    if (category) return { icon: ICON[category], label: item, category };
  }
  const label = reds[0] ?? day.lunch?.[0] ?? '';
  return { icon: '🍚', label, category: null };
}
