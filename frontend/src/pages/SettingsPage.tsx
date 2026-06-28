import React from 'react';
import { useI18n } from '../i18n/useI18n';
import { useSettings } from '../settings/useSettings';
import { TIMEZONE_OPTIONS } from '../settings/settingsContextValue';
import type { Lang } from '../i18n/i18nContextValue';
import { deleteAllData } from '../api';

// SOT-1315: 設定メニュー。言語・標準時間(タイムゾーン)・子どもの名前を設定できる。
// 言語は既存 i18n、タイムゾーン/子どもの名前は SettingsContext に永続化される。
// SOT-1356: 全データ削除（全タスク + 全写真）。破壊的・不可逆のため2段階確認。
const SettingsPage: React.FC = () => {
  const { t, lang, setLang } = useI18n();
  const { timezone, childName, setTimezone, setChildName } = useSettings();

  const [confirming, setConfirming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [result, setResult] = React.useState<{ ok: boolean; message: string } | null>(null);

  const handleDeleteAll = async () => {
    setDeleting(true);
    setResult(null);
    try {
      const { deleted } = await deleteAllData();
      setResult({ ok: true, message: t('settings.deleteAllSuccess').replace('{count}', String(deleted)) });
      setConfirming(false);
    } catch {
      setResult({ ok: false, message: t('settings.deleteAllError') });
    } finally {
      setDeleting(false);
    }
  };

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

      {/* 全データ削除（危険操作） SOT-1356 */}
      <div className="mt-6 bg-surface rounded-2xl shadow-card border border-red-200 p-4 sm:p-6">
        <h2 className="text-base font-bold text-red-600 mb-1">{t('settings.deleteAllTitle')}</h2>
        <p className="text-sm text-muted-foreground mb-4">{t('settings.deleteAllDescription')}</p>

        {!confirming ? (
          <button
            type="button"
            onClick={() => {
              setResult(null);
              setConfirming(true);
            }}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-400"
          >
            {t('settings.deleteAllButton')}
          </button>
        ) : (
          <div className="rounded-lg border border-red-300 bg-red-50 p-4">
            <p className="text-sm font-semibold text-red-700 mb-3">{t('settings.deleteAllConfirm')}</p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleDeleteAll}
                disabled={deleting}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-400 disabled:opacity-50"
              >
                {deleting ? t('settings.deleteAllInProgress') : t('settings.deleteAllConfirmButton')}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={deleting}
                className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-semibold text-foreground hover:bg-muted focus:outline-none focus:ring-2 focus:ring-brand/40 disabled:opacity-50"
              >
                {t('settings.deleteAllCancel')}
              </button>
            </div>
          </div>
        )}

        {result && (
          <p className={`mt-3 text-sm ${result.ok ? 'text-green-600' : 'text-red-600'}`}>{result.message}</p>
        )}
      </div>
    </div>
  );
};

export default SettingsPage;
