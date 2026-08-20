import React from 'react';
import { useI18n } from '../i18n/useI18n';
import type { Child, CareProfile } from '../types';
import { ALLERGEN_KEYS, CARE_CATEGORY_KEYS } from '../pages/careProfileOptions';
import {
  getCareProfiles,
  createCareProfile,
  updateCareProfile,
  deleteCareProfile,
} from '../api';

// SOT-2732: 子ごとの個別配慮プロファイル（アレルゲン/配慮カテゴリ＋自由記述＋重症度メモ）を
// 画面から登録・編集・削除する。設定画面の「お子さまの登録」導線に組み込む。
// 依存: SOT-2729 の /care-profiles CRUD。1子=最大1プロファイルの運用（child_id で絞り込み）。

interface CareProfilePanelProps {
  children: Child[];
}

// updated_at（無ければ created_at）を「最終更新日」として日付表示する。
function formatDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

const CareProfilePanel: React.FC<CareProfilePanelProps> = ({ children }) => {
  const { t } = useI18n();

  const [selectedChildId, setSelectedChildId] = React.useState('');
  const [profile, setProfile] = React.useState<CareProfile | null>(null);

  // フォーム状態。allergens/care_categories は正規形キーの集合。
  const [allergens, setAllergens] = React.useState<Set<string>>(new Set());
  const [careCategories, setCareCategories] = React.useState<Set<string>>(new Set());
  const [freeText, setFreeText] = React.useState('');
  const [severityNote, setSeverityNote] = React.useState('');

  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [confirmingDelete, setConfirmingDelete] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  const resetForm = React.useCallback((p: CareProfile | null) => {
    setProfile(p);
    setAllergens(new Set(p?.allergens ?? []));
    setCareCategories(new Set(p?.care_categories ?? []));
    setFreeText(p?.free_text ?? '');
    setSeverityNote(p?.severity_note ?? '');
  }, []);

  // 子を選ぶたびに、その子のプロファイルを取得してフォームへ反映する。
  // 直近の選択だけを反映するため、リクエストを世代カウンタで識別して古い応答を捨てる。
  const reqSeq = React.useRef(0);

  const handleSelectChild = React.useCallback(
    (childId: string) => {
      setSelectedChildId(childId);
      setError(null);
      setSaved(false);
      setConfirmingDelete(false);
      if (!childId) {
        resetForm(null);
        return;
      }
      const seq = ++reqSeq.current;
      setLoading(true);
      getCareProfiles(childId)
        .then((list) => {
          if (seq !== reqSeq.current) return;
          resetForm(list[0] ?? null);
        })
        .catch(() => {
          if (seq !== reqSeq.current) return;
          resetForm(null);
          setError(t('careProfile.loadError'));
        })
        .finally(() => {
          if (seq === reqSeq.current) setLoading(false);
        });
    },
    [resetForm, t],
  );

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setter(next);
    setSaved(false);
  };

  const handleSave = async () => {
    if (!selectedChildId || saving) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    const payload = {
      allergens: [...allergens],
      care_categories: [...careCategories],
      free_text: freeText.trim() || null,
      severity_note: severityNote.trim() || null,
    };
    try {
      const result = profile
        ? await updateCareProfile(profile.id, payload)
        : await createCareProfile({ child_id: selectedChildId, ...payload });
      resetForm(result);
      setSaved(true);
    } catch {
      setError(t('careProfile.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!profile || deleting) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteCareProfile(profile.id);
      resetForm(null);
      setConfirmingDelete(false);
      setSaved(false);
    } catch {
      setError(t('careProfile.deleteError'));
    } finally {
      setDeleting(false);
    }
  };

  const lastUpdated = formatDate(profile?.updated_at ?? profile?.created_at);

  return (
    <div
      data-testid="care-profile-panel"
      className="mt-6 bg-surface rounded-2xl shadow-card p-4 sm:p-6"
    >
      <h2 className="text-base font-bold text-foreground mb-1">{t('careProfile.title')}</h2>
      <p className="text-sm text-muted-foreground mb-4">{t('careProfile.description')}</p>

      {/* 子選択 */}
      <label className="block text-sm font-semibold text-foreground mb-2">
        {t('careProfile.childLabel')}
      </label>
      <select
        data-testid="care-profile-child-select"
        aria-label={t('careProfile.childLabel')}
        value={selectedChildId}
        onChange={(e) => handleSelectChild(e.target.value)}
        className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
      >
        <option value="">{t('careProfile.childPlaceholder')}</option>
        {children.map((c) => (
          <option key={c.id} value={String(c.id)}>
            {c.name}
            {c.group_name ? `（${c.group_name}）` : ''}
          </option>
        ))}
      </select>

      {children.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">{t('careProfile.noChildren')}</p>
      )}

      {selectedChildId && (
        <div className="mt-4 space-y-5">
          {loading ? (
            <p className="text-sm text-muted-foreground">{t('careProfile.loading')}</p>
          ) : (
            <>
              {/* アレルゲン（型付き属性） */}
              <fieldset>
                <legend className="text-sm font-semibold text-foreground mb-2">
                  {t('careProfile.allergensLabel')}
                </legend>
                <div className="flex flex-wrap gap-2">
                  {ALLERGEN_KEYS.map((key) => {
                    const active = allergens.has(key);
                    return (
                      <button
                        type="button"
                        key={key}
                        aria-pressed={active}
                        onClick={() => toggle(allergens, setAllergens, key)}
                        className={`rounded-full border px-3 py-1 text-sm font-medium transition-colors ${
                          active
                            ? 'border-brand bg-brand text-white'
                            : 'border-border bg-surface text-foreground hover:bg-muted'
                        }`}
                      >
                        {t(`careProfile.allergen.${key}`)}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              {/* 配慮カテゴリ（型付き属性） */}
              <fieldset>
                <legend className="text-sm font-semibold text-foreground mb-2">
                  {t('careProfile.careCategoriesLabel')}
                </legend>
                <div className="flex flex-wrap gap-2">
                  {CARE_CATEGORY_KEYS.map((key) => {
                    const active = careCategories.has(key);
                    return (
                      <button
                        type="button"
                        key={key}
                        aria-pressed={active}
                        onClick={() => toggle(careCategories, setCareCategories, key)}
                        className={`rounded-full border px-3 py-1 text-sm font-medium transition-colors ${
                          active
                            ? 'border-brand bg-brand text-white'
                            : 'border-border bg-surface text-foreground hover:bg-muted'
                        }`}
                      >
                        {t(`careProfile.care.${key}`)}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              {/* 自由記述 */}
              <div>
                <label className="block text-sm font-semibold text-foreground mb-2">
                  {t('careProfile.freeTextLabel')}
                </label>
                <textarea
                  aria-label={t('careProfile.freeTextLabel')}
                  value={freeText}
                  onChange={(e) => {
                    setFreeText(e.target.value);
                    setSaved(false);
                  }}
                  rows={3}
                  placeholder={t('careProfile.freeTextPlaceholder')}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
                />
              </div>

              {/* 重症度メモ */}
              <div>
                <label className="block text-sm font-semibold text-foreground mb-2">
                  {t('careProfile.severityLabel')}
                </label>
                <textarea
                  aria-label={t('careProfile.severityLabel')}
                  value={severityNote}
                  onChange={(e) => {
                    setSeverityNote(e.target.value);
                    setSaved(false);
                  }}
                  rows={2}
                  placeholder={t('careProfile.severityPlaceholder')}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
                />
              </div>

              {/* 最終更新日（保持・表示） */}
              {lastUpdated && (
                <p data-testid="care-profile-updated-at" className="text-xs text-muted-foreground">
                  {t('careProfile.lastUpdated')}: {lastUpdated}
                </p>
              )}
              {profile?.stale_warning && (
                <p className="text-xs text-amber-700">{profile.stale_warning}</p>
              )}

              {/* 操作 */}
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-strong disabled:opacity-50"
                >
                  {saving ? t('careProfile.saving') : t('careProfile.save')}
                </button>
                {profile && !confirmingDelete && (
                  <button
                    type="button"
                    onClick={() => {
                      setConfirmingDelete(true);
                      setSaved(false);
                    }}
                    className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-600 hover:bg-red-50"
                  >
                    {t('careProfile.delete')}
                  </button>
                )}
              </div>

              {profile && confirmingDelete && (
                <div className="rounded-lg border border-red-300 bg-red-50 p-3">
                  <p className="text-sm font-semibold text-red-700 mb-2">
                    {t('careProfile.deleteConfirm')}
                  </p>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={deleting}
                      className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                    >
                      {deleting ? t('careProfile.deleting') : t('careProfile.deleteConfirmButton')}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmingDelete(false)}
                      disabled={deleting}
                      className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-semibold text-foreground hover:bg-muted disabled:opacity-50"
                    >
                      {t('careProfile.cancel')}
                    </button>
                  </div>
                </div>
              )}

              {saved && <p className="text-sm text-green-600">{t('careProfile.saved')}</p>}
              {error && <p className="text-sm text-red-600">{error}</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default CareProfilePanel;
