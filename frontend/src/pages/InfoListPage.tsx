import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getInfoList, getAttachmentFileUrl, deleteInfo } from '../api';
import { useI18n } from '../i18n/useI18n';
import { useConfirm } from '../components/confirmDialogContext';

const INFO_TYPES = ["すべて", "資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"];
// SOT-1355: ステータスを3つに統一（すべて / 未確認 / 未対応 / 対応済）。`確認済` は選択肢から削除。
const STATUS_TYPES = ["すべて", "未確認", "未対応", "対応済"];

const InfoListPage: React.FC = () => {
  const { t } = useI18n();
  const confirm = useConfirm();
  // 表示専用ラベル: フィルタ値・保存値（日本語）は変えず、表示テキストのみ翻訳する
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };
  const [query, setQuery] = useState('');
  const [infoType, setInfoType] = useState('すべて');
  const [status, setStatus] = useState('すべて');
  const [expandedId, setExpandedId] = useState<number | string | null>(null);
  const [deletingId, setDeletingId] = useState<number | string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const { data: items, isLoading } = useQuery({
    queryKey: ['info', query, infoType, status],
    queryFn: () => getInfoList({
      q: query || undefined,
      info_type: infoType === 'すべて' ? undefined : infoType,
      status: status === 'すべて' ? undefined : status,
    }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteInfo,
    onMutate: (id: number | string) => {
      setDeletingId(id);
      setDeleteError(null);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
    },
    onError: () => {
      setDeleteError(t('list.deleteError'));
    },
    onSettled: () => {
      setDeletingId(null);
    },
  });

  const handleDelete = async (e: React.MouseEvent, id: number | string, title: string) => {
    e.stopPropagation();
    if (deleteMutation.isPending) return;
    if (await confirm(t('list.confirmDelete', { title }))) {
      deleteMutation.mutate(id);
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case '高': return 'text-red-600 bg-red-50';
      case '普通': return 'text-brand bg-brand-soft';
      case '低': return 'text-muted-foreground bg-surface-muted';
      default: return 'text-muted-foreground bg-surface-muted';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case '未確認': return 'bg-orange-100 text-orange-800';
      case '未対応': return 'bg-yellow-100 text-yellow-800';
      // SOT-1355: `確認済` は選択肢から削除したが、既存データ表示用に旧値の配色 case は残置（後方互換）。
      case '対応済':
      case '対応済み': return 'bg-green-100 text-green-800';
      case '確認済':
      case '確認済み': return 'bg-brand-soft text-brand-strong';
      default: return 'bg-surface-muted text-foreground';
    }
  };

  return (
    <div className="w-full lg:max-w-6xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('list.title')}</h1>

      <div className="bg-surface p-4 rounded-lg shadow-sm mb-6 grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">{t('list.keyword')}</label>
          <input
            type="text"
            className="w-full border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2 border"
            placeholder={t('list.keywordPlaceholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">{t('list.type')}</label>
          <select
            className="w-full border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2 border"
            value={infoType}
            onChange={(e) => setInfoType(e.target.value)}
          >
            {INFO_TYPES.map(v => <option key={v} value={v}>{v === 'すべて' ? t('options.all') : optLabel('infoType', v)}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">{t('list.status')}</label>
          <select
            className="w-full border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2 border"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {STATUS_TYPES.map(s => <option key={s} value={s}>{s === 'すべて' ? t('options.all') : optLabel('status', s)}</option>)}
          </select>
        </div>
      </div>

      {deleteError && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {deleteError}
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-10 text-muted-foreground">{t('common.loading')}</div>
      ) : !items || items.length === 0 ? (
        <div className="text-center py-10 text-muted-foreground">{t('list.empty')}</div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <div
              key={item.id}
              className="bg-surface rounded-lg shadow-sm border border-border overflow-hidden cursor-pointer hover:border-brand transition-colors"
              onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
            >
              <div className="p-4 sm:flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center space-x-2 mb-1">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-surface-muted text-foreground">
                      {optLabel('infoType', item.info_type)}
                    </span>
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getPriorityColor(item.priority)}`}>
                      {optLabel('priority', item.priority)}
                    </span>
                    {item.attachments && item.attachments.length > 0 && (
                      <span className="inline-flex items-center text-xs text-muted-foreground">
                        <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path>
                        </svg>
                        {item.attachments.length}
                      </span>
                    )}
                  </div>
                  <h3 className="text-lg font-bold text-foreground">{item.title}</h3>
                  <div className="mt-1 text-sm text-muted-foreground space-x-4">
                    {item.date && <span>{t('list.dateLabel')}{item.date}</span>}
                    {item.due_date && <span className="text-red-500 font-semibold">{t('list.dueLabel')}{item.due_date}</span>}
                  </div>
                </div>
                <div className="mt-2 sm:mt-0 flex items-center space-x-2">
                  <span className={`px-3 py-1 rounded-full text-sm font-bold ${getStatusColor(item.status)}`}>
                    {optLabel('status', item.status)}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => handleDelete(e, item.id, item.title)}
                    disabled={deletingId === item.id}
                    className="text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1 rounded-md disabled:text-muted-foreground disabled:hover:bg-transparent transition-colors"
                  >
                    {deletingId === item.id ? t('list.deleting') : t('list.delete')}
                  </button>
                  <div className="text-muted-foreground">
                    {expandedId === item.id ? '▲' : '▼'}
                  </div>
                </div>
              </div>

              {expandedId === item.id && (
                <div className="px-4 pb-4 border-t border-border bg-surface-muted pt-4 animate-fadeIn">
                  <div className="prose prose-sm max-w-none text-foreground whitespace-pre-wrap break-words">
                    {item.content}
                  </div>
                  {item.items && (
                    <div className="mt-4 p-2 bg-brand-soft rounded border border-border">
                      <p className="text-xs font-bold text-brand-strong uppercase tracking-wider mb-1">{t('list.itemsHeading')}</p>
                      <p className="text-sm text-brand-strong break-words">{item.items}</p>
                    </div>
                  )}
                  {item.memo && (
                    <div className="mt-4">
                      <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-1">{t('list.memoHeading')}</p>
                      <p className="text-sm text-muted-foreground italic break-words">{item.memo}</p>
                    </div>
                  )}
                  {item.attachments && item.attachments.length > 0 && (
                    <div className="mt-4">
                      <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('list.attachmentsHeading')}</p>
                      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
                        {item.attachments.map((att) => (
                          <div key={att.id} className="relative group" onClick={(e) => e.stopPropagation()}>
                            {att.mime_type.startsWith('image/') ? (
                              <div className="aspect-square bg-border rounded-md overflow-hidden border border-border">
                                <img
                                  src={getAttachmentFileUrl(att.id)}
                                  alt={att.original_filename}
                                  className="w-full h-full object-cover cursor-pointer hover:opacity-90 transition-opacity"
                                  loading="lazy"
                                  onClick={() => window.open(getAttachmentFileUrl(att.id), '_blank')}
                                />
                              </div>
                            ) : (
                              <a
                                href={getAttachmentFileUrl(att.id)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="aspect-square flex flex-col items-center justify-center bg-surface rounded-md border border-border p-2 hover:bg-surface-muted transition-colors"
                              >
                                <svg className="w-8 h-8 text-muted-foreground mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                                </svg>
                                <span className="text-[10px] text-muted-foreground text-center line-clamp-2 break-all px-1">
                                  {att.original_filename}
                                </span>
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {item.tags && (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {item.tags.split(',').map(tag => (
                        <span key={tag} className="text-xs bg-border text-foreground px-2 py-1 rounded">#{tag.trim()}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default InfoListPage;
