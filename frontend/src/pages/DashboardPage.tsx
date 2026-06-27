import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getToday, getTomorrow, getWeekly, getNextWeek, getReminders } from '../api';
import type { NurseryInfo, ReminderItem, ReminderUrgency } from '../types';
import { useI18n } from '../i18n/useI18n';

// SOT-1080 / 提案5-A: 緊急度ごとの配色（受動表示ではなく能動的に目を引く）。
const URGENCY_STYLES: Record<ReminderUrgency, { row: string; chip: string }> = {
  overdue: { row: 'border-l-4 border-red-500 bg-red-50', chip: 'bg-red-100 text-red-800' },
  today: { row: 'border-l-4 border-amber-500 bg-amber-50', chip: 'bg-amber-100 text-amber-800' },
  soon: { row: 'border-l-4 border-yellow-400 bg-yellow-50', chip: 'bg-yellow-100 text-yellow-800' },
  upcoming: { row: 'border-l-4 border-border bg-surface-muted', chip: 'bg-surface-muted text-foreground' },
};

// SOT-1071: 掲示板（親しみやすい）デザイン。彩度の高い単色ヘッダーをやめ、
// 淡いパステル帯＋絵文字＋柔らかい角丸カードでお知らせボードらしい表現にする。
const DashboardSection: React.FC<{
  title: string;
  items: NurseryInfo[];
  isLoading: boolean;
  renderItem: (item: NurseryInfo) => React.ReactNode;
  emoji: string;
  accentClass: string;
}> = ({ title, items, isLoading, renderItem, emoji, accentClass }) => {
  const { t } = useI18n();
  return (
    <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6">
      <div className={`${accentClass} flex items-center gap-2 px-4 py-3 font-bold`}>
        <span aria-hidden className="text-lg">{emoji}</span>
        <span>{title}</span>
      </div>
      <div className="p-4">
        {isLoading ? (
          <p className="text-muted-foreground">{t('common.loading')}</p>
        ) : items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t('common.noData')}</p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => (
              <li key={item.id}>
                {/* SOT-1281: お知らせをクリックすると一覧の該当ページ（/data/:id）に遷移する */}
                <Link
                  to={`/data/${item.id}`}
                  className="block py-2 -mx-2 px-2 rounded-lg transition-colors hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
                >
                  {renderItem(item)}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

const ReminderRow: React.FC<{ item: ReminderItem }> = ({ item }) => {
  const { t } = useI18n();
  const style = URGENCY_STYLES[item.urgency] ?? URGENCY_STYLES.upcoming;
  return (
    <li className={`flex items-center justify-between gap-3 rounded-lg px-3 py-2 ${style.row}`}>
      <div className="min-w-0">
        <p className="font-medium text-foreground truncate">{item.message}</p>
        <p className="text-xs text-muted-foreground">
          {item.info_type} ・ {item.target_date}
        </p>
      </div>
      <span className={`flex-shrink-0 text-xs px-2 py-1 rounded-full ${style.chip}`}>
        {t(`reminder.urgency.${item.urgency}`)}
      </span>
    </li>
  );
};

const ProactiveReminders: React.FC = () => {
  const { t } = useI18n();
  const remindersQuery = useQuery({ queryKey: ['reminders'], queryFn: () => getReminders(7) });
  const items = remindersQuery.data?.items ?? [];

  if (remindersQuery.isLoading) {
    return (
      <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6">
        <div className="bg-rose-50 text-rose-700 flex items-center gap-2 px-4 py-3 font-bold">
          <span aria-hidden className="text-lg">🔔</span>
          <span>{t('reminder.title')}</span>
        </div>
        <div className="p-4"><p className="text-muted-foreground">{t('common.loading')}</p></div>
      </div>
    );
  }

  if (items.length === 0) return null;

  return (
    <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6 ring-1 ring-rose-100">
      <div className="bg-rose-50 text-rose-700 flex items-center gap-2 px-4 py-3 font-bold">
        <span aria-hidden className="text-lg">🔔</span>
        <span>{t('reminder.title')}</span>
        <span className="ml-auto text-xs font-normal text-rose-500">{t('reminder.subtitle')}</span>
      </div>
      <div className="p-4">
        <ul className="space-y-2">
          {items.map((item) => (
            <ReminderRow key={`${item.kind}-${item.info_id}-${item.target_date}`} item={item} />
          ))}
        </ul>
      </div>
    </div>
  );
};

const DashboardPage: React.FC = () => {
  const { t } = useI18n();
  const todayQuery = useQuery({ queryKey: ['today'], queryFn: getToday });
  const tomorrowQuery = useQuery({ queryKey: ['tomorrow'], queryFn: getTomorrow });
  const weeklyQuery = useQuery({ queryKey: ['weekly'], queryFn: getWeekly });
  const nextWeekQuery = useQuery({ queryKey: ['nextWeek'], queryFn: getNextWeek });

  return (
    <div className="w-full lg:max-w-6xl lg:mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-foreground">{t('dashboard.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('dashboard.subtitle')}</p>

      <ProactiveReminders />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <DashboardSection
          title={t('dashboard.today')}
          items={todayQuery.data || []}
          isLoading={todayQuery.isLoading}
          emoji="📝"
          accentClass="bg-amber-50 text-amber-700"
          renderItem={(item) => (
            <div className="flex justify-between items-center">
              <div>
                <p className="font-medium text-foreground">{item.title}</p>
                {item.due_date && <p className="text-xs text-red-600 font-semibold">{t('dashboard.dueLabel')}{item.due_date}</p>}
              </div>
              <span className="text-xs bg-amber-100 text-amber-800 px-2 py-1 rounded-full">
                {item.info_type}
              </span>
            </div>
          )}
        />

        <DashboardSection
          title={t('dashboard.tomorrow')}
          items={tomorrowQuery.data || []}
          isLoading={tomorrowQuery.isLoading}
          emoji="🎒"
          accentClass="bg-sky-50 text-sky-700"
          renderItem={(item) => (
            <div>
              <p className="font-medium text-foreground">{item.title}</p>
              {item.items && <p className="text-sm text-muted-foreground">{t('dashboard.itemsLabel')}{item.items}</p>}
            </div>
          )}
        />

        <DashboardSection
          title={t('dashboard.weekly')}
          items={weeklyQuery.data || []}
          isLoading={weeklyQuery.isLoading}
          emoji="📅"
          accentClass="bg-emerald-50 text-emerald-700"
          renderItem={(item) => (
            <div className="flex justify-between items-center">
              <span className="font-medium text-foreground">{item.title}</span>
              <span className="text-xs bg-emerald-100 text-emerald-800 px-2 py-1 rounded-full">
                {item.event_date}
              </span>
            </div>
          )}
        />

        <DashboardSection
          title={t('dashboard.nextWeek')}
          items={nextWeekQuery.data || []}
          isLoading={nextWeekQuery.isLoading}
          emoji="🗓️"
          accentClass="bg-indigo-50 text-indigo-700"
          renderItem={(item) => (
            <div className="flex justify-between items-center">
              <span className="font-medium text-foreground">{item.title}</span>
              <span className="text-xs bg-indigo-100 text-indigo-800 px-2 py-1 rounded-full">
                {item.event_date}
              </span>
            </div>
          )}
        />
      </div>
    </div>
  );
};

export default DashboardPage;
