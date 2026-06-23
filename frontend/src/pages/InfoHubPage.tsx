import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n';
import AskPage from './AskPage';
import SearchPage from './SearchPage';
import InfoListPage from './InfoListPage';

// SOT-1053 ページ同一化: 質問 / 検索 / 一覧 を単一ページのセグメント選択式に統合する。
// 各タブは unmount せず `hidden` で表示切替し、入力・結果・取得データの状態を保持する。
type Tab = 'ask' | 'search' | 'list';

const TABS: { id: Tab; labelKey: string }[] = [
  { id: 'ask', labelKey: 'nav.ask' },
  { id: 'search', labelKey: 'nav.search' },
  { id: 'list', labelKey: 'nav.list' },
];

const isTab = (value: string | null): value is Tab =>
  value === 'ask' || value === 'search' || value === 'list';

const InfoHubPage: React.FC = () => {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const param = searchParams.get('tab');
  const activeTab: Tab = isTab(param) ? param : 'ask';

  const selectTab = (tab: Tab) => {
    if (tab === activeTab) return;
    const next = new URLSearchParams(searchParams);
    next.set('tab', tab);
    setSearchParams(next, { replace: true });
  };

  return (
    <div>
      <div
        role="group"
        aria-label={t('nav.info')}
        className="inline-flex items-center rounded-lg overflow-hidden border border-brand/40 bg-surface shadow-sm text-sm font-semibold mb-6"
      >
        {TABS.map((tab) => {
          const selected = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => selectTab(tab.id)}
              aria-pressed={selected}
              aria-selected={selected}
              className={`px-4 py-2 transition-colors ${
                selected
                  ? 'bg-brand text-white'
                  : 'text-foreground hover:bg-brand/10'
              }`}
            >
              {t(tab.labelKey)}
            </button>
          );
        })}
      </div>

      <div className={activeTab === 'ask' ? '' : 'hidden'}>
        <AskPage />
      </div>
      <div className={activeTab === 'search' ? '' : 'hidden'}>
        <SearchPage />
      </div>
      <div className={activeTab === 'list' ? '' : 'hidden'}>
        <InfoListPage />
      </div>
    </div>
  );
};

export default InfoHubPage;
