import React from 'react';
import { Link } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n';

// SOT-1435: アプリの使い方を説明する画面。設定画面の「使い方」ボタンから遷移する。
// 各主要機能をスクショ（図）付きで説明する。スクショは frontend/public/howto/*.png を配信し、
// 画像が無い場合は onError で該当画像だけ隠して文章のみで表示する。
const SECTIONS: Array<{ titleKey: string; bodyKey: string; image: string }> = [
  { titleKey: 'howto.registerTitle', bodyKey: 'howto.registerBody', image: '/howto/register.png' },
  { titleKey: 'howto.tasksTitle', bodyKey: 'howto.tasksBody', image: '/howto/tasks.png' },
  { titleKey: 'howto.deadlineTitle', bodyKey: 'howto.deadlineBody', image: '/howto/agent-demo.png' },
  { titleKey: 'howto.scheduleTitle', bodyKey: 'howto.scheduleBody', image: '/howto/schedule.png' },
  { titleKey: 'howto.boardTitle', bodyKey: 'howto.boardBody', image: '/howto/board.png' },
  { titleKey: 'howto.askTitle', bodyKey: 'howto.askBody', image: '/howto/ask.png' },
  { titleKey: 'howto.settingsTitle', bodyKey: 'howto.settingsBody', image: '/howto/settings.png' },
];

const HowToPage: React.FC = () => {
  const { t } = useI18n();

  return (
    <div className="w-full lg:max-w-2xl lg:mx-auto">
      <div className="flex items-start justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold mb-1 text-foreground">{t('howto.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('howto.subtitle')}</p>
        </div>
        <Link
          to="/settings"
          className="flex-shrink-0 inline-flex items-center gap-1 text-sm font-medium text-brand-strong hover:underline"
        >
          {t('howto.back')}
        </Link>
      </div>

      <div className="space-y-6">
        {SECTIONS.map((s) => (
          <section key={s.titleKey} className="bg-surface rounded-2xl shadow-card p-4 sm:p-6">
            <h2 className="text-base font-bold text-foreground mb-1">{t(s.titleKey)}</h2>
            <p className="text-sm text-muted-foreground mb-3">{t(s.bodyKey)}</p>
            <img
              src={s.image}
              alt={t('howto.imageAlt')}
              loading="lazy"
              className="w-full rounded-lg border border-border"
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
            />
          </section>
        ))}
      </div>
    </div>
  );
};

export default HowToPage;
