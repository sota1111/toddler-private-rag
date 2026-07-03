import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getArchivedList } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import DatedInfoList from '../components/DatedInfoList';

// SOT-1500: アーカイブ一覧。設定画面の「アーカイブを確認」ボタンから遷移する。
// アーカイブした項目（is_archived=true）を、やることリスト(TasksPage)と同じ共有コンポーネント
// DatedInfoList で表示する（月ごとの見出し・期限なし分類つき）。各項目クリックで既存の詳細
// /data/:id へ遷移する。写真本体レコード（添付あり）はやることリストと同じく一覧から除外する。
const ArchivePage: React.FC = () => {
  const { t } = useI18n();
  const { data, isLoading } = useQuery({
    queryKey: ['archived'],
    queryFn: getArchivedList,
  });

  // TasksPage と同様に、写真本体（添付を持つ）レコードは一覧から除外する。
  const events = useMemo<NurseryInfo[]>(
    () => (data ?? []).filter((it) => (it.attachments?.length ?? 0) === 0),
    [data],
  );

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto">
      <div className="bg-surface rounded-2xl shadow-card border border-border overflow-hidden mb-6">
        <div className="flex items-center gap-2 px-4 py-3 bg-accent-bg text-brand-strong font-bold border-b border-accent-border">
          <span aria-hidden className="text-lg">🗄️</span>
          <span>{t('archive.listTitle')}</span>
        </div>
        <DatedInfoList items={events} isLoading={isLoading} namespace="tasks" groupByMonth />
      </div>
    </div>
  );
};

export default ArchivePage;
