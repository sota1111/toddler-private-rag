import React from 'react';
import { Link } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n';
import { useSettings } from '../settings/useSettings';
import { TIMEZONE_OPTIONS } from '../settings/settingsContextValue';
import type { Lang } from '../i18n/i18nContextValue';
import type { Child } from '../types';
import { deleteAllData, getChildren, createChild, deleteChild } from '../api';

// SOT-1315: 設定メニュー。言語・標準時間(タイムゾーン)を設定できる。
// 言語は既存 i18n、タイムゾーンは SettingsContext に永続化される。
// SOT-1356: 全データ削除（全タスク + 全写真）。破壊的・不可逆のため2段階確認。
// SOT-1375: 旧「子どもの名前」欄は削除（お子さまの登録 SOT-1368 に統合）。
const SettingsPage: React.FC = () => {
  const { t, lang, setLang } = useI18n();
  const { timezone, setTimezone, municipality, setMunicipality } = useSettings();

  const [confirming, setConfirming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [result, setResult] = React.useState<{ ok: boolean; message: string } | null>(null);

  // SOT-1436: 市町村「登録」ボタン押下時の確認メッセージ。
  const [municipalityRegistered, setMunicipalityRegistered] = React.useState(false);

  const handleRegisterMunicipality = React.useCallback(() => {
    // 値は onChange で自動保存済みだが、明示的に保存を確定して確認メッセージを出す。
    setMunicipality(municipality);
    setMunicipalityRegistered(true);
  }, [municipality, setMunicipality]);

  React.useEffect(() => {
    if (!municipalityRegistered) return;
    const id = window.setTimeout(() => setMunicipalityRegistered(false), 2500);
    return () => window.clearTimeout(id);
  }, [municipalityRegistered]);

  // SOT-1368: お子さまの登録・管理。
  const [children, setChildren] = React.useState<Child[]>([]);
  const [newChildName, setNewChildName] = React.useState('');
  const [childBusy, setChildBusy] = React.useState(false);
  const [childError, setChildError] = React.useState<string | null>(null);

  React.useEffect(() => {
    getChildren()
      .then(setChildren)
      .catch(() => {
        /* 一覧取得失敗は致命的でない。空のまま表示する。 */
      });
  }, []);

  const handleAddChild = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newChildName.trim();
    if (!name || childBusy) return;
    setChildBusy(true);
    setChildError(null);
    try {
      const created = await createChild(name);
      setChildren((prev) => [...prev, created]);
      setNewChildName('');
    } catch {
      setChildError(t('settings.childrenAddError'));
    } finally {
      setChildBusy(false);
    }
  };

  const handleDeleteChild = async (id: number | string) => {
    try {
      await deleteChild(id);
      setChildren((prev) => prev.filter((c) => c.id !== id));
    } catch {
      setChildError(t('settings.childrenAddError'));
    }
  };

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
      <div className="flex items-start justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold mb-1 text-foreground">{t('settings.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('settings.subtitle')}</p>
        </div>
        <Link
          to="/howto"
          className="flex-shrink-0 inline-flex items-center gap-1 rounded-lg border border-brand/40 px-3 py-2 text-sm font-semibold text-brand-strong hover:bg-brand/10"
        >
          {t('settings.howtoButton')}
        </Link>
      </div>

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

        {/* 市町村 (SOT-1403) */}
        <div>
          <label className="block text-sm font-semibold text-foreground mb-2">
            {t('settings.municipality')}
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              aria-label={t('settings.municipality')}
              value={municipality}
              onChange={(e) => {
                setMunicipality(e.target.value);
                setMunicipalityRegistered(false);
              }}
              placeholder={t('settings.municipalityPlaceholder')}
              className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
            />
            <button
              type="button"
              onClick={handleRegisterMunicipality}
              className="shrink-0 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-strong focus:outline-none focus:ring-2 focus:ring-brand/40"
            >
              {t('settings.municipalityRegister')}
            </button>
          </div>
          {municipalityRegistered && (
            <p className="mt-2 text-sm text-brand-strong">{t('settings.municipalityRegistered')}</p>
          )}
        </div>
      </div>

      {/* お子さまの登録・管理 (SOT-1368) */}
      <div className="mt-6 bg-surface rounded-2xl shadow-card p-4 sm:p-6">
        <h2 className="text-base font-bold text-foreground mb-1">{t('settings.childrenTitle')}</h2>
        <p className="text-sm text-muted-foreground mb-4">{t('settings.childrenDescription')}</p>

        {children.length === 0 ? (
          <p className="text-sm text-muted-foreground mb-4">{t('settings.childrenEmpty')}</p>
        ) : (
          <ul className="mb-4 space-y-2">
            {children.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between rounded-lg border border-border bg-surface px-3 py-2"
              >
                <span className="text-sm text-foreground">{c.name}</span>
                <button
                  type="button"
                  onClick={() => handleDeleteChild(c.id)}
                  className="rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                >
                  {t('settings.childrenDelete')}
                </button>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={handleAddChild} className="flex gap-2">
          <input
            type="text"
            aria-label={t('settings.childrenTitle')}
            value={newChildName}
            onChange={(e) => setNewChildName(e.target.value)}
            placeholder={t('settings.childrenPlaceholder')}
            className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
          />
          <button
            type="submit"
            disabled={childBusy || newChildName.trim().length === 0}
            className="shrink-0 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-strong disabled:opacity-50"
          >
            {t('settings.childrenAdd')}
          </button>
        </form>
        {childError && <p className="mt-2 text-sm text-red-600">{childError}</p>}
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
