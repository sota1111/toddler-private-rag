import React, { useMemo, useState } from 'react';
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
}

const DatedInfoList: React.FC<DatedInfoListProps> = ({ items, isLoading, namespace, beforeList }) => {
  const { t } = useI18n();
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
  const favoriteMutation = useMutation({
    mutationFn: ({ id, value }: { id: number | string; value: boolean }) =>
      updateInfo(id, { is_favorite: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info'] });
      ['today', 'tomorrow', 'weekly', 'nextWeek'].forEach((k) =>
        queryClient.invalidateQueries({ queryKey: [k] }));
    },
  });
  const showFavorite = namespace === 'tasks';

  const [statusFilter, setStatusFilter] = useState<DatedInfoStatusFilter>('all');

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

  return (
    <>
      {/* ステータス絞り込み（すべて / 未確認 / 未対応 / 対応済）。未選択時は全ピル共通デザイン。 */}
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
      <div className="p-4">
        {beforeList}
        {isLoading ? (
          <p className="text-muted-foreground">{t('common.loading')}</p>
        ) : listItems.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t('common.noData')}</p>
        ) : (
          <ul className="divide-y divide-border">
            {listItems.map((item) => (
              <li key={item.id}>
                <Link
                  to={`/data/${item.id}`}
                  className="block py-2 -mx-2 px-2 rounded-lg transition-colors hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
                >
                  <div className="flex justify-between items-center gap-3">
                    <span className="font-medium text-foreground truncate">{item.title}</span>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {/* SOT-1368 follow-up: 紐づけた子どもの名前タグ（子どもごとの色）。未指定/未解決は非表示。 */}
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
                      <span className="text-xs text-muted-foreground">{optLabel('infoType', item.info_type)}</span>
                      {/* SOT-1428: お気に入りトグル。行リンク内なので遷移を抑止する。お気に入り時は黄色塗り潰し。 */}
                      {showFavorite && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            favoriteMutation.mutate({ id: item.id, value: !item.is_favorite });
                          }}
                          disabled={favoriteMutation.isPending}
                          aria-pressed={!!item.is_favorite}
                          aria-label={t(item.is_favorite ? 'favorite.remove' : 'favorite.add')}
                          title={t(item.is_favorite ? 'favorite.remove' : 'favorite.add')}
                          className="flex-shrink-0 rounded-full p-0.5 transition-colors hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40 disabled:opacity-50"
                        >
                          <FavoriteStar filled={!!item.is_favorite} />
                        </button>
                      )}
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
};

export default DatedInfoList;
