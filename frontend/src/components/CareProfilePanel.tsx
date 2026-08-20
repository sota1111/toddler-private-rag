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

  // SOT-2746: 設定内容の確認（一覧化）用に、全児の登録済みプロファイルを保持する。
  // 行タップでそのお子さまの編集に入れる。保存/削除のたびに再取得して同期する。
  const [allProfiles, setAllProfiles] = React.useState<CareProfile[]>([]);

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

  // SOT-2746: 登録済み一覧を取得（child_id なし = 全児）。失敗は致命的でないので黙って空のまま。
  const reloadAllProfiles = React.useCallback(() => {
    getCareProfiles()
      .then((list) => setAllProfiles(list))
      .catch(() => {
        /* 一覧取得失敗は致命的でない。 */
      });
  }, []);

  React.useEffect(() => {
    reloadAllProfiles();
  }, [reloadAllProfiles]);

  // SOT-2746: お子さまが1名だけなら自動選択して即編集できるようにする（設定しやすく）。
  const autoSelectedRef = React.useRef(false);
  React.useEffect(() => {
    if (autoSelectedRef.current || selectedChildId) return;
    if (children.length === 1) {
      autoSelectedRef.current = true;
      // 同期 setState を避けるためマイクロタスクへ逃がす（react-hooks/set-state-in-effect）。
      const id = String(children[0].id);
      queueMicrotask(() => handleSelectChild(id));
    }
  }, [children, selectedChildId, handleSelectChild]);

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
      reloadAllProfiles();
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
      reloadAllProfiles();
    } catch {
      setError(t('careProfile.deleteError'));
    } finally {
      setDeleting(false);
    }
  };

  const lastUpdated = formatDate(profile?.updated_at ?? profile?.created_at);

  // SOT-2746: 現存するお子さまに紐づく登録済みプロファイルだけを一覧に出す（子の順序に揃える）。
  const childName = React.useCallback(
    (childId: string): string => {
      const c = children.find((ch) => String(ch.id) === String(childId));
      if (!c) return childId;
      return c.group_name ? `${c.name}（${c.group_name}）` : c.name;
    },
    [children],
  );
  const knownProfiles = React.useMemo(
    () =>
      children
        .map((c) => allProfiles.find((p) => String(p.child_id) === String(c.id)))
        .filter((p): p is CareProfile => Boolean(p)),
    [children, allProfiles],
  );

  return (
    <div
      data-testid="care-profile-panel"
      className="mt-6 bg-surface rounded-2xl shadow-card p-4 sm:p-6"
    >
      <h2 className="text-base font-bold text-foreground mb-1">{t('careProfile.title')}</h2>
      <p className="text-sm text-muted-foreground mb-4">{t('careProfile.description')}</p>

      {/* SOT-2746: 登録済み一覧（設定内容の確認）。全児の登録内容をチップで俯瞰し、
          行タップでそのお子さまの編集に入れる。子が未登録のときは出さない。 */}
      {children.length > 0 && (
        <div data-testid="care-profile-summary" className="mb-5">
          <h3 className="text-sm font-semibold text-foreground mb-1">
            {t('careProfile.registeredTitle')}
          </h3>
          {knownProfiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('careProfile.registeredEmpty')}</p>
          ) : (
            <>
              <p className="text-xs text-muted-foreground mb-2">{t('careProfile.registeredHint')}</p>
              <ul className="space-y-2">
                {knownProfiles.map((p) => {
                  const name = childName(p.child_id);
                  const hasAttrs = p.allergens.length > 0 || p.care_categories.length > 0;
                  return (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => handleSelectChild(String(p.child_id))}
                        className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-left hover:bg-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
                      >
                        <span className="text-sm font-semibold text-foreground">{name}</span>
                        {hasAttrs ? (
                          <span className="mt-1 flex flex-wrap gap-1.5">
                            {p.allergens.map((key) => (
                              <span
                                key={`a-${key}`}
                                className="rounded-full border border-red-300 bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800"
                              >
                                {t(`careProfile.allergen.${key}`)}
                              </span>
                            ))}
                            {p.care_categories.map((key) => (
                              <span
                                key={`c-${key}`}
                                className="rounded-full border border-brand/30 bg-brand/10 px-2 py-0.5 text-xs font-medium text-brand-strong"
                              >
                                {t(`careProfile.care.${key}`)}
                              </span>
                            ))}
                          </span>
                        ) : (
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            {t('careProfile.registeredNoAttrs')}
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      )}

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
