import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getInfoList } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import DatedInfoList from '../components/DatedInfoList';

// SOT-1313: カレンダー画面（SchedulePage）の「カレンダーの下の予定一覧」と同じ内容を、
// 独立した「タスク一覧」メニューとして表示する。各項目クリックで既存の詳細 /data/:id へ遷移する。
// SOT-1342: 予定一覧との重複する一覧部分（ステータス絞り込み + 行リスト）を共有コンポーネント
// DatedInfoList に1箇所化（タスク一覧が正）。

const TasksPage: React.FC = () => {
  const { t } = useI18n();
  const { data, isLoading } = useQuery({
    queryKey: ['info', 'all'],
    queryFn: () => getInfoList({ include_attachments: false }),
  });

  // 日付つきの予定のみを対象にする。
  const events = useMemo<NurseryInfo[]>(
    () => (data ?? []).filter((item) => Boolean(item.event_date)),
    [data],
  );

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-foreground">{t('tasks.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('tasks.subtitle')}</p>

      <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6">
        <div className="flex items-center gap-2 px-4 py-3 bg-emerald-50 text-emerald-700 font-bold">
          <span aria-hidden className="text-lg">📅</span>
          <span>{t('tasks.listTitle')}</span>
        </div>
        <DatedInfoList items={events} isLoading={isLoading} namespace="tasks" />
      </div>
    </div>
  );
};

export default TasksPage;
