import type { MenuDay } from '../types';

// menu-calendar: 献立カレンダーのセル表示用。
// SOT-2746: セルに出す文字は「主菜のたんぱく源名」ではなく給食(lunch)の主菜の料理名
// （例「酒の醤油豆腐マヨネーズ焼き」）にする。アイコンはその主菜のたんぱく源を肉/魚/豆に分類する。
// 主菜が特定できない場合は「体をつくる（赤）」列(main_ingredients.red)から分類にフォールバックする。
// 以前は分類できないと🍚（ご飯）を出していたが、主食（ごはん）ではなく主菜を示すため汎用の🍽️にする。

export type ProteinCategory = '肉' | '魚' | '豆';

// 主菜ではない主食・汁物・飲み物・デザート等（料理名から主菜を選ぶときにスキップする）。
const NON_MAIN_DISH = [
  'ごはん', 'ご飯', 'ライス', '白飯', '米飯', '飯', 'ふりかけ', 'パン', 'トースト',
  'うどん', 'そうめん', 'ラーメン', 'スパゲ', 'マカロニ', '焼きそば',
  '味噌汁', 'みそ汁', 'すまし汁', 'スープ', '汁', '牛乳', 'ミルク', 'お茶', 'ゼリー',
  'ヨーグルト', 'プリン', 'フルーツ', '果物', 'みかん', 'りんご', 'バナナ', 'デザート',
];

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
// 主菜のたんぱく源を分類できないときの汎用アイコン（ご飯🍚は出さない: SOT-2746）。
const FALLBACK_ICON = '🍽️';

// 文字列（食材名 or 料理名）を魚→肉→豆の順で分類する。分類対象外は null。
function classifyItem(item: string): ProteinCategory | null {
  if (SKIP.some((k) => item.includes(k))) return null;
  if (FISH.some((k) => item.includes(k))) return '魚';
  if (MEAT.some((k) => item.includes(k))) return '肉';
  if (BEAN.some((k) => item.includes(k))) return '豆';
  return null;
}

// 料理名の分類は SKIP を無視する（料理名に「だし」等が含まれても主菜判定は残す）。
function classifyDish(dish: string): ProteinCategory | null {
  if (FISH.some((k) => dish.includes(k))) return '魚';
  if (MEAT.some((k) => dish.includes(k))) return '肉';
  if (BEAN.some((k) => dish.includes(k))) return '豆';
  return null;
}

const isMainDishCandidate = (dish: string): boolean =>
  dish.trim().length > 0 && !NON_MAIN_DISH.some((k) => dish.includes(k));

export interface MenuProtein {
  icon: string;
  label: string;
  category: ProteinCategory | null;
}

// SOT-2746: セルに出す主菜を1つ選ぶ。
// 1) 給食(lunch)から主食・汁物等を除いた料理を候補にし、たんぱく源を分類できた最初の料理を主菜とする
//    → 文字は料理名（例「酒の醤油豆腐マヨネーズ焼き」）、アイコンはその分類。
// 2) 分類できる料理が無ければ、主食等でない先頭の料理名を出し、アイコンは赤列の食材から分類する。
// 3) それも無ければ赤列先頭 or 給食先頭を文字に、アイコンは汎用（🍽️）。
export function pickMenuProtein(day: MenuDay): MenuProtein {
  const lunch = day.lunch ?? [];
  const reds = day.main_ingredients?.red ?? [];
  const candidates = lunch.filter(isMainDishCandidate);

  // 1) 主菜の料理名から分類できたものを最優先で採用。
  for (const dish of candidates) {
    const category = classifyDish(dish);
    if (category) return { icon: ICON[category], label: dish, category };
  }

  // 2) 料理名からは分類できない。文字は主菜候補の先頭、アイコンは赤列食材の分類にフォールバック。
  const dishLabel = candidates[0] ?? lunch[0] ?? '';
  for (const item of reds) {
    const category = classifyItem(item);
    if (category) {
      return { icon: ICON[category], label: dishLabel || item, category };
    }
  }

  // 3) 何も分類できない: ご飯アイコンは出さず汎用アイコンにする。
  const label = dishLabel || reds[0] || '';
  return { icon: FALLBACK_ICON, label, category: null };
}
