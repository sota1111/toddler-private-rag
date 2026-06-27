import React from 'react';
import { useI18n } from '../i18n/useI18n';
import { useSettings } from '../settings/useSettings';
import { TIMEZONE_OPTIONS } from '../settings/settingsContextValue';
import type { Lang } from '../i18n/i18nContextValue';

// SOT-1315: 設定メニュー。言語・標準時間(タイムゾーン)・子どもの名前を設定できる。
// 言語は既存 i18n、タイムゾーン/子どもの名前は SettingsContext に永続化される。
const SettingsPage: React.FC = () => {
  const { t, lang, setLang } = useI18n();
  const { timezone, childName, setTimezone, setChildName } = useSettings();

  return (
    <div className="w-full lg:max-w-2xl lg:mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-foreground">{t('settings.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('settings.subtitle')}</p>

      <div className="bg-surface rounded-2xl shadow-card p-4 sm:p-6 space-y-6">
        {/* 言語 */}
        <div>
          <label className="block text-sm font-semibold text-foreground mb-2">
            {t('settings.language')}
          </label>
          <select
            aria-label={t('settings.language')}
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
          >
            <option value="ja">日本語</option>
            <option value="en">English</option>
          </select>
        </div>

        {/* 標準時間（タイムゾーン） */}
        <div>
          <label className="block text-sm font-semibold text-foreground mb-2">
            {t('settings.timezone')}
          </label>
          <select
            aria-label={t('settings.timezone')}
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
          >
            {TIMEZONE_OPTIONS.map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </select>
        </div>

        {/* 子どもの名前 */}
        <div>
          <label className="block text-sm font-semibold text-foreground mb-2">
            {t('settings.childName')}
          </label>
          <input
            type="text"
            aria-label={t('settings.childName')}
            value={childName}
            onChange={(e) => setChildName(e.target.value)}
            placeholder={t('settings.childNamePlaceholder')}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
          />
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
