import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { hybridSearch, getAttachmentFileUrl } from '../api';
import type { HybridSearchResponse } from '../types';
import { useI18n } from '../i18n/useI18n';

const INFO_TYPES = ['すべて', '資料', '掲示', '行事', '持ち物', '提出物', 'お知らせ', '給食', '休園変更', '市町村'];
// SOT-1355: ステータスを3つに統一（すべて / 未確認 / 未対応 / 対応済）。`確認済` は選択肢から削除。
const STATUS_TYPES = ['すべて', '未確認', '未対応', '対応済'];
const PRIORITY_TYPES = ['すべて', '高', '普通', '低'];

interface SearchParams {
  q?: string;
  info_type?: string;
  status?: string;
  priority?: string;
  tag?: string;
  date_from?: string;
  date_to?: string;
}

// SOT-1039 / 提案6: ハイブリッド検索（ベクトル+キーワード+ファセット）
const SearchPage: React.FC = () => {
  const { t } = useI18n();
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const [query, setQuery] = useState('');
  const [infoType, setInfoType] = useState('すべて');
  const [status, setStatus] = useState('すべて');
  const [priority, setPriority] = useState('すべて');
  const [tag, setTag] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [submitted, setSubmitted] = useState<SearchParams | null>(null);

  const { data, isLoading, isError } = useQuery<HybridSearchResponse>({
    queryKey: ['hybrid-search', submitted],
    queryFn: () => hybridSearch(submitted ?? {}),
    enabled: submitted !== null,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted({
      q: query.trim() || undefined,
      info_type: infoType === 'すべて' ? undefined : infoType,
      status: status === 'すべて' ? undefined : status,
      priority: priority === 'すべて' ? undefined : priority,
      tag: tag.trim() || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    });
  };

  const getPriorityColor = (p: string) => {
    switch (p) {
      case '高': return 'text-red-600 bg-red-50';
      case '普通': return 'text-brand bg-brand-soft';
      case '低': return 'text-muted-foreground bg-surface-muted';
      default: return 'text-muted-foreground bg-surface-muted';
    }
  };

  const matchedLabel = (m: string) => {
    const key = `search.matched.${m}`;
    const label = t(key);
    return label === key ? m : label;
  };

  return (
    <div className="w-full lg:max-w-5xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-2 text-foreground">{t('search.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('search.desc')}</p>

      <form onSubmit={handleSubmit} className="bg-surface p-4 rounded-lg shadow-sm mb-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">{t('search.keyword')}</label>
          <input
            type="text"
            className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
            placeholder={t('search.keywordPlaceholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t('list.type')}</label>
            <select
              className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
              value={infoType}
              onChange={(e) => setInfoType(e.target.value)}
            >
              {INFO_TYPES.map(v => <option key={v} value={v}>{v === 'すべて' ? t('options.all') : optLabel('infoType', v)}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t('list.status')}</label>
            <select
              className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              {STATUS_TYPES.map(s => <option key={s} value={s}>{s === 'すべて' ? t('options.all') : optLabel('status', s)}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldPriority')}</label>
            <select
              className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              {PRIORITY_TYPES.map(p => <option key={p} value={p}>{p === 'すべて' ? t('options.all') : optLabel('priority', p)}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t('search.tag')}</label>
            <input
              type="text"
              className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
              placeholder={t('search.tagPlaceholder')}
              value={tag}
              onChange={(e) => setTag(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t('search.dateFrom')}</label>
            <input
              type="date"
              className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t('search.dateTo')}</label>
            <input
              type="date"
              className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={isLoading}
            className="px-5 py-2 rounded-md text-sm font-medium text-white bg-brand hover:bg-brand-strong disabled:bg-border disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? t('search.searching') : t('search.submit')}
          </button>
        </div>
      </form>

      {isError && (
        <div className="mb-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {t('search.error')}
        </div>
      )}

      {isLoading && (
        <div className="text-center py-10 text-muted-foreground">{t('common.loading')}</div>
      )}

      {!isLoading && submitted && data && data.results.length === 0 && (
        <div className="text-center py-10 text-muted-foreground">{t('search.empty')}</div>
      )}

      {!isLoading && data && data.results.length > 0 && (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">{t('search.resultCount', { count: String(data.results.length) })}</p>
          {data.results.map(({ info, score, vector_score, keyword_score, matched_by }) => (
            <div key={info.id} className="bg-surface rounded-lg shadow-sm border border-border p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-surface-muted text-foreground">
                      {optLabel('infoType', info.info_type)}
                    </span>
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getPriorityColor(info.priority)}`}>
                      {optLabel('priority', info.priority)}
                    </span>
                    {info.attachments && info.attachments.length > 0 && (
                      <span className="inline-flex items-center text-xs text-muted-foreground">📎 {info.attachments.length}</span>
                    )}
                  </div>
                  <h3 className="text-lg font-bold text-foreground break-words">{info.title}</h3>
                  <p className="mt-1 text-sm text-muted-foreground line-clamp-2 break-words">{info.content}</p>
                  <div className="mt-1 text-xs text-muted-foreground space-x-3">
                    {info.date && <span>{t('list.dateLabel')}{info.date}</span>}
                    {info.due_date && <span className="text-red-500 font-semibold">{t('list.dueLabel')}{info.due_date}</span>}
                  </div>
                </div>
                <div className="flex-shrink-0 text-right">
                  <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-semibold bg-indigo-50 text-indigo-700">
                    {t('search.relevance')} {score.toFixed(2)}
                  </span>
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    K {keyword_score.toFixed(2)} / V {vector_score.toFixed(2)}
                  </div>
                </div>
              </div>

              {matched_by.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {matched_by.map((m) => (
                    <span key={m} className="text-[10px] bg-brand-soft text-brand-strong px-1.5 py-0.5 rounded">
                      {matchedLabel(m)}
                    </span>
                  ))}
                </div>
              )}

              {info.tags && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {info.tags.split(',').map(tg => tg.trim()).filter(Boolean).map(tg => (
                    <span key={tg} className="text-xs bg-border text-foreground px-2 py-0.5 rounded">#{tg}</span>
                  ))}
                </div>
              )}

              {info.attachments && info.attachments.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {info.attachments.filter(a => a.mime_type.startsWith('image/')).slice(0, 4).map((att) => (
                    <img
                      key={att.id}
                      src={getAttachmentFileUrl(att.id)}
                      alt={att.original_filename}
                      className="h-14 w-14 object-cover rounded border border-border cursor-pointer hover:opacity-90"
                      loading="lazy"
                      onClick={() => window.open(getAttachmentFileUrl(att.id), '_blank')}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SearchPage;
