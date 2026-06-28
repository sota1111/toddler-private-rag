import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getInfoList } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import { getStatusDateChipClass } from './infoFormOptions';

// SOT-1313: カレンダー画面（SchedulePage）の「カレンダーの下の予定一覧」と同じ内容を、
// 独立した「タスク一覧」メニューとして表示する。各項目クリックで既存の詳細 /data/:id へ遷移する。

const TasksPage: React.FC = () => {
  const { t } = useI18n();
  // 種別ラベル（保存値は日本語のまま、表示は設定言語に合わせて翻訳）
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };
  const { data, isLoading } = useQuery({
    queryKey: ['info', 'all'],
    queryFn: () => getInfoList({ include_attachments: false }),
  });

  // SOT-1314: ステータスで表示内容を絞り込めるようにする。
  // SOT-1344: ステータス集合・順序・表記を統一（すべて → 未確認 → 確認済 → 未対応 → 対応済）。
  // 'all' は全件、それ以外は実在ステータス値で絞る。
  type StatusFilter = 'all' | '未確認' | '確認済' | '未対応' | '対応済';
  const STATUS_FILTERS: { key: StatusFilter; labelKey: string }[] = [
    { key: 'all', labelKey: 'tasks.showAll' },
    { key: '未確認', labelKey: 'tasks.showUnconfirmed' },
    { key: '確認済', labelKey: 'tasks.showConfirmed' },
    { key: '未対応', labelKey: 'tasks.showPending' },
    { key: '対応済', labelKey: 'tasks.showDone' },
  ];
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  // 日付つきの予定のみを対象にする。
  const events = useMemo<NurseryInfo[]>(
    () => (data ?? []).filter((item) => Boolean(item.event_date)),
    [data],
  );

  // 日付昇順。ステータスフィルタが 'all' 以外のときは該当ステータスのみ。
  const listItems = useMemo<NurseryInfo[]>(() => {
    let filtered = events;
    if (statusFilter !== 'all') {
      filtered = filtered.filter((ev) => ev.status === statusFilter);
    }
    return [...filtered].sort((a, b) =>
      (a.event_date as string).localeCompare(b.event_date as string),
    );
  }, [events, statusFilter]);

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-foreground">{t('tasks.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('tasks.subtitle')}</p>

      <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6">
        <div className="flex items-center gap-2 px-4 py-3 bg-emerald-50 text-emerald-700 font-bold">
          <span aria-hidden className="text-lg">📅</span>
          <span>{t('tasks.listTitle')}</span>
        </div>
        {/* ステータス絞り込み（すべて / 未確認 / 確認済 / 未対応 / 対応済） */}
        <div className="flex flex-wrap gap-2 px-4 pt-3" role="group" aria-label={t('tasks.listTitle')}>
          {STATUS_FILTERS.map(({ key, labelKey }) => {
            const active = statusFilter === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setStatusFilter(key)}
                aria-pressed={active}
                className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-colors focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                  active
                    ? 'bg-brand text-white border-brand'
                    : 'bg-surface text-foreground border-border hover:bg-surface-muted'
                }`}
              >
                {t(labelKey)}
              </button>
            );
          })}
        </div>
        <div className="p-4">
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
      </div>
    </div>
  );
};

export default TasksPage;
