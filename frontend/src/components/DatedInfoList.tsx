import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import { getChildren, updateInfo } from '../api';
import FavoriteStar from './FavoriteStar';
import {
  getStatusDateChipClass,
  getStatusFilterPillClass,
  getChildColorClasses,
} from '../pages/infoFormOptions';

// SOT-1342: タスク一覧（TasksPage）と予定一覧（SchedulePage のカレンダー下リスト）の
// 重複していた「ステータス絞り込み + 行リスト」を1箇所にまとめた共有コンポーネント。
// タスク一覧を正（canonical）とし、行マークアップは TasksPage のものを採用する。
// 質問の一覧（Ask 出典リスト）は性質が異なるため対象外（このコンポーネントは使わない）。

export type DatedInfoStatusFilter = 'all' | '未確認' | '未対応' | '対応済';

// SOT-1355: ステータスを3つに統一（すべて → 未確認 → 未対応 → 対応済）。`確認済` は削除。
// ラベルキーは namespace（'tasks' | 'schedule'）と組み合わせて解決する。
const STATUS_FILTERS: { key: DatedInfoStatusFilter; suffix: string }[] = [
  { key: 'all', suffix: 'showAll' },
  { key: '未確認', suffix: 'showUnconfirmed' },
  { key: '未対応', suffix: 'showPending' },
  { key: '対応済', suffix: 'showDone' },
];

interface DatedInfoListProps {
  // 一覧項目。呼び出し側で前段フィルタ済み（SchedulePage は event_date ありかつ selectedDate 適用後を渡す）。
  // SOT-1365: TasksPage は日付不明（event_date 無し）の項目も渡しうる（チップは「期限なし」表示・末尾ソート）。
  // ステータス絞り込みとソートは本コンポーネントが行う。
  items: NurseryInfo[];
  isLoading: boolean;
  // i18n の名前空間。ピルのラベルキーと role group の aria-label に使う。
  namespace: 'tasks' | 'schedule';
  // 一覧本文(p-4)の先頭、ローディング/リストより前に差し込む内容
  // （SchedulePage の絞り込み中インジケータ用）。
  beforeList?: React.ReactNode;
  // SOT-1502: やることリストを月ごとの見出しでグループ表示し、期限なしを末尾グループにまとめる。
  // 既定 false（SchedulePage は従来どおりのフラット表示のまま）。
  groupByMonth?: boolean;
  // SOT-1557: 行にカテゴリ（種別 = info_type: 行事/お知らせ/給食 等）ラベルを表示するか。
  // 既定 true（SchedulePage / ArchivePage は従来どおり表示）。やることリスト(TasksPage)のみ
  // false を渡してカテゴリ表示を非表示にする。
  showCategory?: boolean;
}

const DatedInfoList: React.FC<DatedInfoListProps> = ({
  items,
  isLoading,
  namespace,
  beforeList,
  groupByMonth = false,
  showCategory = true,
}) => {
  const { t, lang } = useI18n();
  // 種別ラベル（保存値は日本語のまま、表示は設定言語に合わせて翻訳）
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  // SOT-1368 follow-up: 行に紐づけた子どもの名前タグを表示するため children を取得する。
  // react-query は同一キーをデデュープするため TasksPage 等と並行でも安全。
  const { data: children } = useQuery({ queryKey: ['children'], queryFn: getChildren });
  const childList = children ?? [];

  // SOT-1428: お気に入りトグル。やることリスト(namespace='tasks')の行にのみ星ボタンを出す。
  // 更新後はやることリスト(['info',...])と掲示板(today/tomorrow/weekly/nextWeek)を再取得する。
  const queryClient = useQueryClient();
  // SOT-1430: タップ→黄色までのラグ解消のため楽観的更新を行う。星の黄色表示は is_favorite に
  // 束縛されており、従来は onSuccess の再取得完了後にしか反映されなかった。onMutate でキャッシュを
  // 即時反映し、失敗時は onError でロールバック、onSettled でサーバ値へ再同期する。
  const FAVORITE_QUERY_KEYS = [['info'], ['today'], ['tomorrow'], ['weekly'], ['nextWeek']];
  const favoriteMutation = useMutation({
    mutationFn: ({ id, value }: { id: number | string; value: boolean }) =>
      updateInfo(id, { is_favorite: value }),
    onMutate: async ({ id, value }: { id: number | string; value: boolean }) => {
      // 楽観的更新の間は進行中の再取得を止め、上書きが巻き戻されないようにする。
      await Promise.all(
        FAVORITE_QUERY_KEYS.map((queryKey) => queryClient.cancelQueries({ queryKey })),
      );
      const patch = (old: unknown): unknown => {
        const flip = (it: NurseryInfo) =>
          String(it.id) === String(id) ? { ...it, is_favorite: value } : it;
        if (Array.isArray(old)) return (old as NurseryInfo[]).map(flip);
        if (old && typeof old === 'object' && 'id' in (old as NurseryInfo))
          return flip(old as NurseryInfo);
        return old;
      };
      // 触れる全キャッシュをスナップショットしてから楽観的に書き換える。
      const snapshots = FAVORITE_QUERY_KEYS.flatMap((queryKey) => {
        const entries = queryClient.getQueriesData({ queryKey });
        queryClient.setQueriesData({ queryKey }, patch);
        return entries;
      });
      return { snapshots };
    },
    onError: (_err, _vars, context) => {
      // 失敗時は全スナップショットを元のキーへ復元（星を元の状態に戻す）。
      context?.snapshots.forEach(([queryKey, data]) => queryClient.setQueryData(queryKey, data));
    },
    onSettled: () => {
      FAVORITE_QUERY_KEYS.forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
    },
  });
  const showFavorite = namespace === 'tasks';

  const [statusFilter, setStatusFilter] = useState<DatedInfoStatusFilter>('all');

  // SOT-1505: 月グループごとに折りたたみ（表示/非表示）できるようにする。
  // 既定は全月展開。逆三角ボタンで各月の項目リストの表示/非表示を切り替える。
  const [collapsedMonths, setCollapsedMonths] = useState<Set<string>>(() => new Set());
  const toggleMonth = (key: string) => {
    setCollapsedMonths((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // SOT-1506: 凡例（ステータス絞り込み行）を固定し、その下の月グループ本体だけをスクロール
  // 可能にする。初回データ表示時に一度だけスクロール位置を現在月のグループへ合わせ、上下スクロールで
  // 前後の月を確認できるようにする。以降の再描画（お気に入りトグル等）ではユーザーのスクロール位置を尊重する。
  const scrollRef = useRef<HTMLDivElement>(null);
  const didInitialScroll = useRef(false);

  // ステータス絞り込み（'all' 以外は該当ステータスのみ）→ event_date 昇順ソート。
  // SOT-1365: event_date が空（日付不明 = 期限なし）の項目は末尾に回す。
  const listItems = useMemo<NurseryInfo[]>(() => {
    const filtered =
      statusFilter === 'all' ? items : items.filter((ev) => ev.status === statusFilter);
    return [...filtered].sort((a, b) => {
      const da = a.event_date ?? '';
      const db = b.event_date ?? '';
      if (!da && !db) return 0;
      if (!da) return 1; // 日付なし（期限なし）は末尾
      if (!db) return -1;
      return da.localeCompare(db);
    });
  }, [items, statusFilter]);

  // SOT-1502: 月ごとの見出しでグループ化する（groupByMonth のときだけ使用）。
  // listItems は日付昇順＋期限なし末尾で並んでいるため、初出順に辿るだけで
  // 月グループは昇順・期限なしグループは末尾になる。
  const monthHeading = (yyyymm: string) => {
    const year = Number(yyyymm.slice(0, 4));
    const month1 = Number(yyyymm.slice(5, 7)); // 1-12
    if (lang === 'ja') return `${year}年${month1}月`;
    return new Date(year, month1 - 1, 1).toLocaleDateString('en', {
      year: 'numeric',
      month: 'long',
    });
  };
  const NO_DEADLINE_KEY = '__no_deadline__';
  const groups = useMemo(() => {
    const result: { key: string; heading: string; items: NurseryInfo[] }[] = [];
    const index = new Map<string, number>();
    for (const item of listItems) {
      const date = item.event_date ?? '';
      const dated = /^\d{4}-\d{2}/.test(date);
      const key = dated ? date.slice(0, 7) : NO_DEADLINE_KEY;
      const heading = dated ? monthHeading(key) : t('common.noDeadline');
      let i = index.get(key);
      if (i === undefined) {
        i = result.length;
        index.set(key, i);
        result.push({ key, heading, items: [] });
      }
      result[i].items.push(item);
    }
    return result;
    // monthHeading は lang に依存するため lang を依存に含める。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listItems, lang, t]);

  // SOT-1506: 初回データ表示時に一度だけ、現在月（無ければ現在月以降で最も近い月、それも無ければ
  // 末尾の月）のグループ見出しをスクロール先頭に合わせる。
  useLayoutEffect(() => {
    if (!groupByMonth || didInitialScroll.current || isLoading || groups.length === 0) return;
    const container = scrollRef.current;
    if (!container) return;
    const now = new Date();
    const currentKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    const dated = groups.filter((g) => g.key !== NO_DEADLINE_KEY);
    const target =
      dated.find((g) => g.key === currentKey) ??
      dated.find((g) => g.key >= currentKey) ??
      dated[dated.length - 1] ??
      groups[0];
    const el = target
      ? container.querySelector<HTMLElement>(`[data-month-key="${target.key}"]`)
      : null;
    if (el) container.scrollTop = el.offsetTop;
    didInitialScroll.current = true;
  }, [groupByMonth, isLoading, groups]);

  const renderItem = (item: NurseryInfo) => (
    <li key={item.id}>
      <Link
        to={`/data/${item.id}`}
        className="block py-2 -mx-2 px-2 rounded-lg transition-colors hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
      >
        <div className="flex justify-between items-center gap-3">
          <span className="font-medium text-foreground truncate">{item.title}</span>
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* SOT-1368 follow-up: 紐づけた子どもの名前タグ（子どもごとの色）。未指定/未解決は非表示。 */}
            {/* SOT-1552 REOPEN: やることリスト一覧では子どもの名前のみ表示する（組/クラスは設定画面のみ）。 */}
            {(() => {
              if (!item.child_id) return null;
              const child = childList.find((c) => String(c.id) === String(item.child_id));
              if (!child) return null;
              return (
                <span
                  className={`text-xs px-2 py-1 rounded-full max-w-[6rem] truncate ${getChildColorClasses(item.child_id, childList).chip}`}
                >
                  {child.name}
                </span>
              );
            })()}
            <span className={`text-xs px-2 py-1 rounded-full ${getStatusDateChipClass(item.status)}`}>
              {item.event_date ? item.event_date : t('common.noDeadline')}
            </span>
            {/* SOT-1557: カテゴリ（種別）ラベル。やることリストでは非表示（showCategory=false）。 */}
            {showCategory && (
              <span className="text-xs text-muted-foreground">{optLabel('infoType', item.info_type)}</span>
            )}
            {/* SOT-1428: お気に入りトグル。行リンク内なので遷移を抑止する。お気に入り時は黄色塗り潰し。 */}
            {showFavorite && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  favoriteMutation.mutate({ id: item.id, value: !item.is_favorite });
                }}
                aria-pressed={!!item.is_favorite}
                aria-label={t(item.is_favorite ? 'favorite.remove' : 'favorite.add')}
                title={t(item.is_favorite ? 'favorite.remove' : 'favorite.add')}
                className="flex-shrink-0 rounded-full p-0.5 transition-colors hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
              >
                <FavoriteStar filled={!!item.is_favorite} />
              </button>
            )}
          </div>
        </div>
      </Link>
    </li>
  );

  const body = (
    <div className="p-4">
      {beforeList}
        {isLoading ? (
          <p className="text-muted-foreground">{t('common.loading')}</p>
        ) : listItems.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t('common.noData')}</p>
        ) : groupByMonth ? (
          // SOT-1502: 月ごとの見出し（期限あり）＋末尾の「期限なし」グループで表示する。
          // SOT-1505: 見出しと同じ高さに逆三角ボタンを置き、その月の表示/非表示を切り替える。
          groups.map((group) => {
            const collapsed = collapsedMonths.has(group.key);
            return (
              <div key={group.key} data-month-key={group.key} className="mb-4 last:mb-0">
                <div className="mb-1 flex items-center gap-2">
                  <h3 className="text-sm font-bold text-muted-foreground">{group.heading}</h3>
                  <button
                    type="button"
                    onClick={() => toggleMonth(group.key)}
                    aria-expanded={!collapsed}
                    aria-label={t(collapsed ? 'tasks.expandMonth' : 'tasks.collapseMonth', {
                      month: group.heading,
                    })}
                    title={t(collapsed ? 'tasks.expandMonth' : 'tasks.collapseMonth', {
                      month: group.heading,
                    })}
                    className="flex-shrink-0 rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
                  >
                    <span
                      aria-hidden="true"
                      className={`inline-block text-xs leading-none transition-transform ${collapsed ? '-rotate-90' : ''}`}
                    >
                      ▼
                    </span>
                  </button>
                </div>
                {!collapsed && (
                  <ul className="divide-y divide-border">{group.items.map(renderItem)}</ul>
                )}
              </div>
            );
          })
        ) : (
          <ul className="divide-y divide-border">{listItems.map(renderItem)}</ul>
        )}
    </div>
  );

  return (
    <>
      {/* ステータス絞り込み（すべて / 未確認 / 未対応 / 対応済）。未選択時は全ピル共通デザイン。 */}
      {/* SOT-1506: この凡例行はスクロール領域の外に置き、常に固定表示する。 */}
      <div className="flex flex-wrap gap-2 px-4 pt-3" role="group" aria-label={t(`${namespace}.listTitle`)}>
        {STATUS_FILTERS.map(({ key, suffix }) => {
          const active = statusFilter === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setStatusFilter(key)}
              aria-pressed={active}
              className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-colors focus:outline-none focus:ring-2 focus:ring-brand/40 ${getStatusFilterPillClass(key, active)}`}
            >
              {t(`${namespace}.${suffix}`)}
            </button>
          );
        })}
      </div>
      {/* SOT-1506: やることリスト（groupByMonth）は本体だけをスクロール可能にし、初期は現在月へ位置づける。
          SchedulePage（groupByMonth 無し）は従来どおりスクロール枠なしで表示する。 */}
      {groupByMonth ? (
        <div ref={scrollRef} className="relative max-h-[60vh] overflow-y-auto">
          {body}
        </div>
      ) : (
        body
      )}
    </>
  );
};

export default DatedInfoList;
