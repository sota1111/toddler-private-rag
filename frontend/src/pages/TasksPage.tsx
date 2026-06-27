import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getInfoList } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';

// SOT-1313: カレンダー画面（SchedulePage）の「カレンダーの下の予定一覧」と同じ内容を、
// 独立した「タスク一覧」メニューとして表示する。各項目クリックで既存の詳細 /data/:id へ遷移する。

const TasksPage: React.FC = () => {
  const { t } = useI18n();
  const { data, isLoading } = useQuery({
    queryKey: ['info', 'all'],
    queryFn: () => getInfoList({ include_attachments: false }),
  });

  // SchedulePage の一覧と同じく「すべて」/「対応済みのみ」で切り替える。
  const [statusFilter, setStatusFilter] = useState<'all' | 'done'>('all');

  // 日付つきの予定のみを対象にする。
  const events = useMemo<NurseryInfo[]>(
    () => (data ?? []).filter((item) => Boolean(item.event_date)),
    [data],
  );

  // 日付昇順。ステータスフィルタが 'done' のときは「対応済み」のみ。
  const listItems = useMemo<NurseryInfo[]>(() => {
    let filtered = events;
    if (statusFilter === 'done') {
      filtered = filtered.filter((ev) => ev.status === '対応済み');
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
        {/* 「すべて / 対応済み」表示切替 */}
        <div className="flex gap-2 px-4 pt-3" role="group" aria-label={t('tasks.listTitle')}>
          {(['all', 'done'] as const).map((key) => {
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
                {key === 'all' ? t('tasks.showAll') : t('tasks.showDone')}
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
                        <span className="text-xs bg-emerald-100 text-emerald-800 px-2 py-1 rounded-full">
                          {item.event_date}
                        </span>
                        <span className="text-xs text-muted-foreground">{item.info_type}</span>
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
