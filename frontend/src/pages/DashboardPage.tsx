import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTomorrow, getWeekly, getPending } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';

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
    <div className="bg-white rounded-2xl shadow-card overflow-hidden mb-6">
      <div className={`${accentClass} flex items-center gap-2 px-4 py-3 font-bold`}>
        <span aria-hidden className="text-lg">{emoji}</span>
        <span>{title}</span>
      </div>
      <div className="p-4">
        {isLoading ? (
          <p className="text-gray-500">{t('common.loading')}</p>
        ) : items.length === 0 ? (
          <p className="text-gray-400 text-sm">{t('common.noData')}</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {items.map((item) => (
              <li key={item.id} className="py-2">
                {renderItem(item)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

const DashboardPage: React.FC = () => {
  const { t } = useI18n();
  const tomorrowQuery = useQuery({ queryKey: ['tomorrow'], queryFn: getTomorrow });
  const weeklyQuery = useQuery({ queryKey: ['weekly'], queryFn: getWeekly });
  const pendingQuery = useQuery({ queryKey: ['pending'], queryFn: getPending });

  return (
    <div className="w-full lg:max-w-6xl lg:mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-gray-800">{t('dashboard.title')}</h1>
      <p className="text-sm text-gray-500 mb-6">{t('dashboard.subtitle')}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <DashboardSection
          title={t('dashboard.tomorrow')}
          items={tomorrowQuery.data || []}
          isLoading={tomorrowQuery.isLoading}
          emoji="🎒"
          accentClass="bg-sky-50 text-sky-700"
          renderItem={(item) => (
            <div>
              <p className="font-medium text-gray-800">{item.title}</p>
              {item.items && <p className="text-sm text-gray-600">{t('dashboard.itemsLabel')}{item.items}</p>}
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
              <span className="font-medium text-gray-800">{item.title}</span>
              <span className="text-xs bg-emerald-100 text-emerald-800 px-2 py-1 rounded-full">
                {item.event_date}
              </span>
            </div>
          )}
        />

        <DashboardSection
          title={t('dashboard.pending')}
          items={pendingQuery.data || []}
          isLoading={pendingQuery.isLoading}
          emoji="📮"
          accentClass="bg-rose-50 text-rose-700"
          renderItem={(item) => (
            <div className="flex justify-between items-center">
              <div>
                <p className="font-medium text-gray-800">{item.title}</p>
                {item.due_date && <p className="text-xs text-red-600 font-semibold">{t('dashboard.dueLabel')}{item.due_date}</p>}
              </div>
              <span className="text-xs bg-rose-100 text-rose-800 px-2 py-1 rounded-full">
                {item.priority}
              </span>
            </div>
          )}
        />
      </div>
    </div>
  );
};

export default DashboardPage;
