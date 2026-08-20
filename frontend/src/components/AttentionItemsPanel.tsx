import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAttentionItems, reviewAttentionItem, getChildren } from '../api';
import type { AttentionItem, AttentionReviewStatus, Child } from '../types';
import { useI18n } from '../i18n/useI18n';
import { getChildColorClasses } from '../pages/infoFormOptions';

// SOT-2734: 「⚠ 要確認（この子向け）」レーン。おたより登録時に照合エンジン(SOT-2733)が生成した
// 根拠付き項目を、既存の注意事項カテゴリとは**別レーン**で併記する。保護者が根拠（なぜ）を確認し、
// 確認済/非該当（誤検出）を分類できる（人間が最終判断）。断定表現は出さない（要確認/情報不足のみ）。

const CONFIDENCE_CHIP: Record<string, string> = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-slate-100 text-slate-700',
};

const ChildNameChip: React.FC<{ childId: string | null | undefined; children: Child[] }> = ({
  childId,
  children,
}) => {
  if (!childId) return null;
  const child = children.find((c) => String(c.id) === String(childId));
  if (!child) return null;
  return (
    <span
      className={`text-xs px-2 py-1 rounded-full max-w-[6rem] truncate ${getChildColorClasses(childId, children).chip}`}
    >
      {child.name}
    </span>
  );
};

const AttentionCard: React.FC<{ item: AttentionItem; children: Child[] }> = ({ item, children }) => {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [showWhy, setShowWhy] = useState(false);

  const mutation = useMutation({
    mutationFn: (reviewStatus: AttentionReviewStatus) => reviewAttentionItem(item.id, reviewStatus),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['attentionItems'] });
    },
  });

  const reviewed = item.review_status !== 'unreviewed';
  const notApplicable = item.review_status === 'not_applicable';
  const ev = item.evidence ?? {};
  const confKey = `attention.confidence.${item.confidence}`;
  const confLabel = t(confKey) === confKey ? item.confidence : t(confKey);
  const sourceKey = ev.source ? `attention.source.${ev.source}` : '';
  const sourceLabel = sourceKey && t(sourceKey) !== sourceKey ? t(sourceKey) : ev.source ?? '';

  // 状態バッジ（要確認 / 情報不足のため要確認）。断定はしない。
  const statusKey = `attention.status.${item.status}`;
  const statusLabel = t(statusKey) === statusKey ? t('attention.status.attention') : t(statusKey);

  return (
    <li
      className={`rounded-lg border-l-4 px-3 py-2 ${
        notApplicable ? 'border-slate-300 bg-slate-50 opacity-70' : 'border-red-500 bg-red-50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span aria-hidden>⚠️</span>
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-white/70 text-red-700 border border-red-200">
              {statusLabel}
            </span>
            <span
              className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
                CONFIDENCE_CHIP[item.confidence] ?? 'bg-slate-100 text-slate-700'
              }`}
            >
              {t('attention.evidenceConfidence')}: {confLabel}
            </span>
            {reviewed && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-200 text-slate-700">
                {t(`attention.reviewed.${item.review_status}`)}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm font-medium text-foreground break-words">{item.message}</p>
        </div>
        <ChildNameChip childId={item.child_id} children={children} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setShowWhy((v) => !v)}
          aria-expanded={showWhy}
          className="text-xs font-medium px-2 py-1 rounded-md border border-red-200 text-red-700 hover:bg-white/60"
        >
          {showWhy ? t('attention.whyHide') : t('attention.why')}
        </button>
        <span className="flex-1" />
        {!reviewed ? (
          <>
            <button
              type="button"
              disabled={mutation.isPending}
              onClick={() => mutation.mutate('confirmed')}
              className="text-xs font-medium px-3 py-1 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {t('attention.confirm')}
            </button>
            <button
              type="button"
              disabled={mutation.isPending}
              onClick={() => mutation.mutate('not_applicable')}
              className="text-xs font-medium px-3 py-1 rounded-md border border-border text-foreground hover:bg-surface-muted disabled:opacity-50"
            >
              {t('attention.notApplicable')}
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate('unreviewed')}
            className="text-xs font-medium px-3 py-1 rounded-md border border-border text-muted-foreground hover:bg-surface-muted disabled:opacity-50"
          >
            {t('attention.reset')}
          </button>
        )}
      </div>

      {showWhy && (
        <dl className="mt-2 rounded-md bg-white/70 border border-red-100 p-2 text-xs text-foreground space-y-1">
          {ev.span && (
            <div className="flex gap-2">
              <dt className="font-semibold text-muted-foreground shrink-0">{t('attention.evidenceSpan')}:</dt>
              <dd className="break-words">{ev.span}</dd>
            </div>
          )}
          {ev.profile_item && (
            <div className="flex gap-2">
              <dt className="font-semibold text-muted-foreground shrink-0">{t('attention.evidenceProfile')}:</dt>
              <dd className="break-words">{ev.profile_item}</dd>
            </div>
          )}
          <div className="flex gap-2">
            <dt className="font-semibold text-muted-foreground shrink-0">{t('attention.evidenceConfidence')}:</dt>
            <dd>{confLabel}</dd>
          </div>
          {sourceLabel && (
            <div className="flex gap-2">
              <dt className="font-semibold text-muted-foreground shrink-0">{t('attention.evidenceSource')}:</dt>
              <dd>{sourceLabel}</dd>
            </div>
          )}
          {item.llm_notes && item.llm_notes.length > 0 && (
            <div className="flex gap-2">
              <dt className="font-semibold text-muted-foreground shrink-0">{t('attention.source.llm')}:</dt>
              <dd className="break-words">{item.llm_notes.join(' / ')}</dd>
            </div>
          )}
        </dl>
      )}
    </li>
  );
};

// SOT-2746: 掲示板の「要確認」は直近1週間の項目のみ表示する（古い照合結果で掲示板を埋めない）。
const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;
// SOT-2746: バックエンド(SQLite 経路)はタイムゾーン指定の無い ISO 文字列で日時を返すため、
// そのまま new Date() に渡すと**ローカル時刻**として解釈され、7日境界がタイムゾーン差ぶんズレる。
// タイムゾーン指定（Z / ±hh:mm）が無い場合は UTC とみなして絶対時刻の比較を正確化する。
const parseTimestampMs = (value: string): number => {
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(value.trim());
  return new Date(hasTz ? value : `${value}Z`).getTime();
};

// SOT-2746: 「直近1週間」の基準は項目の**生成時刻(created_at)ではなく、項目が指す献立/おたよりの日付**。
// 生成は最近でも古い献立（例: 先月分）の要確認が残り続けるのを防ぐ。参照日は
//   (1) 根拠 locator.date（献立日）→ (2) 文面中の日付（ISO / 「M月D日」）→ (3) created_at
// の順に解決する（決定的で構造化された情報を優先）。
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;
const parseDateOnlyMs = (value: string): number => new Date(`${value}T00:00:00Z`).getTime();
const referenceDateMs = (item: AttentionItem): number => {
  const loc = item.evidence?.locator?.date;
  if (typeof loc === 'string' && DATE_ONLY_RE.test(loc.trim())) {
    const ms = parseDateOnlyMs(loc.trim());
    if (!Number.isNaN(ms)) return ms;
  }
  const msg = item.message ?? '';
  const iso = msg.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (iso) {
    const ms = parseDateOnlyMs(`${iso[1]}-${iso[2]}-${iso[3]}`);
    if (!Number.isNaN(ms)) return ms;
  }
  // 「M月D日」（LLM 文脈確認など、年の記載が無い和文）。年は当年を基準にし、半年以上先なら前年とみなす。
  const jp = msg.match(/(\d{1,2})月(\d{1,2})日/);
  if (jp) {
    const now = Date.now();
    const year = new Date(now).getUTCFullYear();
    let ms = Date.UTC(year, Number(jp[1]) - 1, Number(jp[2]));
    if (ms - now > 183 * 24 * 60 * 60 * 1000) ms = Date.UTC(year - 1, Number(jp[1]) - 1, Number(jp[2]));
    if (!Number.isNaN(ms)) return ms;
  }
  return parseTimestampMs(item.created_at);
};
// 参照日が7日より古い項目だけを隠す。未来日（これからの献立）や日付不明はフェイルオープンで残す。
const isWithinRecentWindow = (item: AttentionItem): boolean => {
  const ref = referenceDateMs(item);
  if (Number.isNaN(ref)) return true;
  return Date.now() - ref <= ONE_WEEK_MS;
};

const AttentionItemsPanel: React.FC = () => {
  const { t } = useI18n();
  const attentionQuery = useQuery({ queryKey: ['attentionItems'], queryFn: () => getAttentionItems() });
  const childrenQuery = useQuery({ queryKey: ['children'], queryFn: getChildren });
  const childList = childrenQuery.data ?? [];

  // SOT-2746: (1) 確認済/非該当（レビュー済み）は掲示板から消す＝未確認のみ表示、
  //           (2) 参照する献立/おたよりの日付が直近1週間のものだけに絞り込む。
  const sorted = (attentionQuery.data ?? [])
    .filter((item) => item.review_status === 'unreviewed')
    .filter(isWithinRecentWindow);

  // 項目が無いときは（読み込み後は）レーンごと非表示にして掲示板を汚さない。
  if (attentionQuery.isLoading || sorted.length === 0) return null;

  return (
    <div
      className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6 ring-1 ring-red-100"
      data-testid="attention-items-panel"
    >
      <div className="bg-red-50 text-red-700 flex items-center gap-2 px-4 py-3 font-bold">
        <span aria-hidden className="text-lg">⚠️</span>
        <span className="whitespace-nowrap">{t('attention.title')}</span>
        {/* SOT-2746: 直近1週間フィルタが効いていることを常時可視化し、動作を確認できるようにする。 */}
        <span
          className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-white/70 text-red-700 border border-red-200 whitespace-nowrap"
          data-testid="attention-recent-window"
        >
          {t('attention.recentWindow')}
        </span>
        <span className="ml-auto text-xs font-normal text-red-500 hidden sm:inline">
          {t('attention.subtitle')}
        </span>
      </div>
      <div className="p-4">
        <ul className="space-y-2">
          {sorted.map((item) => (
            <AttentionCard key={item.id} item={item} children={childList} />
          ))}
        </ul>
      </div>
    </div>
  );
};

export default AttentionItemsPanel;
