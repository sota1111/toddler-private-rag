import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import { getStatusDateChipClass } from '../pages/infoFormOptions';

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
  // 日付つき（event_date あり）の項目。呼び出し側で前段フィルタ済み
  // （SchedulePage は selectedDate 適用後を渡す）。ステータス絞り込みとソートは本コンポーネントが行う。
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

  const [statusFilter, setStatusFilter] = useState<DatedInfoStatusFilter>('all');

  // ステータス絞り込み（'all' 以外は該当ステータスのみ）→ event_date 昇順ソート。
  const listItems = useMemo<NurseryInfo[]>(() => {
    const filtered =
      statusFilter === 'all' ? items : items.filter((ev) => ev.status === statusFilter);
    return [...filtered].sort((a, b) =>
      (a.event_date as string).localeCompare(b.event_date as string),
    );
  }, [items, statusFilter]);

  return (
    <>
      {/* ステータス絞り込み（すべて / 未確認 / 未対応 / 対応済）。未選択時は全ピル共通デザイン。 */}
      <div className="flex flex-wrap gap-1 px-4 pt-3" role="group" aria-label={t(`${namespace}.listTitle`)}>
        {STATUS_FILTERS.map(({ key, suffix }) => {
          const active = statusFilter === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setStatusFilter(key)}
              aria-pressed={active}
              className={`px-2 py-1.5 text-xs font-medium rounded-full border transition-colors focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                active
                  ? 'bg-brand text-white border-brand'
                  : 'bg-surface text-foreground border-border hover:bg-surface-muted'
              }`}
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
                      <span className={`text-xs px-2 py-1 rounded-full ${getStatusDateChipClass(item.status)}`}>
                        {item.event_date}
                      </span>
                      <span className="text-xs text-muted-foreground">{optLabel('infoType', item.info_type)}</span>
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
