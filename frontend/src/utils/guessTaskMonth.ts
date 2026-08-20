// SOT-2790: 期限なし（event_date 無し）のタスクでも「該当月」を推測し、やることリストの
// その月のグループに表示するためのヘルパー。
//
// 推測の考え方（保守的な既定・表示上の補助であることに留意）:
//   1. タスクのテキスト（タイトル/持ち物/メモ/タグ/本文）から月の言及を探す。
//      - 「2026年9月」「2026-09」「2026/9」のように **年+月が明示** されていればそれを採用。
//      - 「9月」のように **月だけ** の言及は、そのタスクの登録日(created_at)を起点に年を補完する
//        （登録月以降の最も近いその月＝先回り準備アプリの性質に合わせ未来方向へ寄せる）。
//   2. テキストから月が取れないときは登録日(created_at)の月を「該当月」とする。
//   3. それも解決できないときだけ null を返す（呼び出し側で従来どおり「期限なし」グループへ）。
//
// 返り値は 'YYYY-MM'（未解決時 null）。イベント日(event_date)がある通常タスクは呼び出し側で
// event_date を使うため、本関数は event_date 無しのタスクにのみ用いる。

export interface GuessTaskMonthLike {
  title?: string | null;
  content?: string | null;
  items?: string | null;
  memo?: string | null;
  tags?: string | null;
  created_at?: string | null;
}

// 年+月を明示する表記: 2026年9月 / 2026-09 / 2026/9 （区切りは 年・- ・/）。
const YEAR_MONTH_RE = /(\d{4})\s*[年\-/.]\s*(\d{1,2})(?!\d)/;
// 月のみの表記: 9月 / 12月。前が数字（日付や電話番号の一部）でない位置を優先する。
const MONTH_ONLY_RE = /(?<!\d)(\d{1,2})\s*月/;

const pad2 = (n: number) => String(n).padStart(2, '0');

const isValidMonth = (m: number) => Number.isInteger(m) && m >= 1 && m <= 12;

/** created_at（ISO 文字列）から { year, month } を取り出す。無効なら null。 */
function anchorFromCreatedAt(createdAt?: string | null): { year: number; month: number } | null {
  if (!createdAt) return null;
  const m = /^(\d{4})-(\d{2})/.exec(String(createdAt));
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  if (!isValidMonth(month)) return null;
  return { year, month };
}

/**
 * 期限なしタスクの「該当月」を 'YYYY-MM' で推測する。解決できなければ null。
 */
export function guessTaskMonth(item: GuessTaskMonthLike): string | null {
  const anchor = anchorFromCreatedAt(item.created_at);

  // テキストは信頼度の高い順（タイトル→持ち物→メモ→タグ→本文）に走査する。
  const fields = [item.title, item.items, item.memo, item.tags, item.content];
  for (const raw of fields) {
    if (!raw) continue;
    const text = String(raw);

    // まず年+月の明示表記。
    const ym = YEAR_MONTH_RE.exec(text);
    if (ym) {
      const year = Number(ym[1]);
      const month = Number(ym[2]);
      if (isValidMonth(month)) return `${year}-${pad2(month)}`;
    }

    // 次に月のみの表記。年は created_at を起点に未来方向へ補完する。
    const mo = MONTH_ONLY_RE.exec(text);
    if (mo) {
      const month = Number(mo[1]);
      if (isValidMonth(month)) {
        if (anchor) {
          const year = month >= anchor.month ? anchor.year : anchor.year + 1;
          return `${year}-${pad2(month)}`;
        }
        // created_at が無い場合でも月は分かるので、年はそのまま補完不能 → 本文月として null 扱いにせず
        // 登録日フォールバックへ委ねる（下）。
      }
    }
  }

  // テキストから決められなければ登録月にフォールバック。
  if (anchor) return `${anchor.year}-${pad2(anchor.month)}`;
  return null;
}
