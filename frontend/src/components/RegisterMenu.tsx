import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n';

// SOT-1174 メニュー改善: 手動登録 / 自動登録 / 仮登録 を「アイコン＋テキスト」の同一メニューに統合する。
// 各登録ページ上部に共通表示し、ここから相互に切り替えられる。初期画面(ナビの「登録」)は自動登録。

type RegisterMenuItem = {
  to: string;
  labelKey: string;
  icon: React.ReactNode;
  isActive: (pathname: string) => boolean;
};

const iconClass = 'h-6 w-6';
const iconProps = {
  xmlns: 'http://www.w3.org/2000/svg',
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  className: iconClass,
  'aria-hidden': true,
};

const ITEMS: RegisterMenuItem[] = [
  {
    // 自動登録 (写真からOCR) — カメラ + きらめき
    to: '/create/auto',
    labelKey: 'nav.createAuto',
    isActive: (p) => p === '/create/auto',
    icon: (
      <svg {...iconProps}>
        <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h12" />
        <circle cx="9" cy="13" r="3" />
        <path d="M18 3v4M16 5h4" />
      </svg>
    ),
  },
  {
    // 手動登録 (フォーム入力) — ペン
    to: '/create',
    labelKey: 'nav.createManual',
    isActive: (p) => p === '/create',
    icon: (
      <svg {...iconProps}>
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
      </svg>
    ),
  },
  {
    // 仮登録 (一時保存一覧) — クリップボード
    to: '/drafts',
    labelKey: 'nav.drafts',
    isActive: (p) => p === '/drafts',
    icon: (
      <svg {...iconProps}>
        <path d="M9 2h6a1 1 0 0 1 1 1v2H8V3a1 1 0 0 1 1-1z" />
        <path d="M16 4h2a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
        <path d="M9 12h6M9 16h4" />
      </svg>
    ),
  },
];

const RegisterMenu: React.FC = () => {
  const { t } = useI18n();
  const { pathname } = useLocation();

  return (
    <nav
      aria-label={t('nav.create')}
      className="mb-6 grid grid-cols-3 gap-2 sm:inline-flex sm:gap-3"
    >
      {ITEMS.map((item) => {
        const active = item.isActive(pathname);
        return (
          <Link
            key={item.to}
            to={item.to}
            aria-current={active ? 'page' : undefined}
            className={`flex flex-col items-center justify-center gap-1 rounded-xl border px-3 py-3 text-sm font-semibold transition-colors sm:px-5 ${
              active
                ? 'border-brand bg-brand text-white shadow-sm'
                : 'border-border bg-surface text-foreground hover:border-brand/40 hover:bg-brand/10'
            }`}
          >
            {item.icon}
            <span className="whitespace-nowrap">{t(item.labelKey)}</span>
          </Link>
        );
      })}
    </nav>
  );
};

export default RegisterMenu;
