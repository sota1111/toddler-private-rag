import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getInfoList } from '../api';
import { useI18n } from '../i18n/useI18n';

// SOT-1217: 本登録データの一覧ページ。タイトルのみを表示し、選択すると詳細ページへ画面遷移する。
const DataListPage: React.FC = () => {
  const { t } = useI18n();
  const navigate = useNavigate();

  const { data: items, isLoading } = useQuery({
    // 既存 InfoListPage と同じ ['info'] 名前空間（フィルタ無しの本登録一覧）
    queryKey: ['info', '', 'すべて', 'すべて'],
    queryFn: () => getInfoList(),
  });

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('records.title')}</h1>

      {isLoading ? (
        <div className="text-center py-10 text-muted-foreground">{t('common.loading')}</div>
      ) : !items || items.length === 0 ? (
        <div className="text-center py-10 text-muted-foreground">{t('records.empty')}</div>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => navigate(`/data/${item.id}`)}
                className="w-full text-left bg-surface rounded-lg shadow-sm border border-border px-4 py-3 flex items-center justify-between gap-3 cursor-pointer hover:border-brand transition-colors"
              >
                <span className="font-semibold text-foreground truncate">{item.title}</span>
                <span className="text-muted-foreground flex-shrink-0" aria-hidden>›</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default DataListPage;
