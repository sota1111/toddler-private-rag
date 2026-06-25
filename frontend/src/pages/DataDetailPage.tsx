import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { getInfoById, updateInfo, deleteInfo, getAttachmentFileUrl } from '../api';
import { useI18n } from '../i18n/useI18n';
import { INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES } from './infoFormOptions';
import type { NurseryInfo, NurseryInfoCreate } from '../types';

// SOT-1217: データ一覧の詳細ページ。内容と元画像を確認でき、編集・削除も可能。
// id ごとに key 付きで再マウントすることで、別レコードへ遷移したときに編集状態を確実にリセットする。
const DataDetail: React.FC<{ id: number }> = ({ id }) => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // 表示専用ラベル: 保存値（日本語）は変えず、表示テキストのみ翻訳する（InfoListPage と同方針）
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState<NurseryInfoCreate | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data: item, isLoading, isError } = useQuery({
    queryKey: ['info-detail', id],
    queryFn: () => getInfoById(id),
    enabled: Number.isFinite(id),
  });

  const toForm = (info: NurseryInfo): NurseryInfoCreate => ({
    title: info.title,
    info_type: info.info_type,
    content: info.content,
    date: info.date ?? '',
    event_date: info.event_date ?? '',
    due_date: info.due_date ?? '',
    items: info.items ?? '',
    status: info.status,
    priority: info.priority,
    tags: info.tags ?? '',
    memo: info.memo ?? '',
  });

  const startEdit = () => {
    if (!item) return;
    setForm(toForm(item));
    setSaveError(null);
    setIsEditing(true);
  };

  const cancelEdit = () => {
    setIsEditing(false);
    setForm(null);
    setSaveError(null);
  };

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => {
    const { name, value } = e.target;
    setForm((prev) => (prev ? { ...prev, [name]: value } : prev));
  };

  const updateMutation = useMutation({
    mutationFn: (data: NurseryInfoCreate) => updateInfo(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info-detail', id] });
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
      setIsEditing(false);
      setForm(null);
    },
    onError: () => setSaveError(t('records.saveError')),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteInfo(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
      navigate('/data');
    },
    onError: () => setDeleteError(t('records.deleteError')),
  });

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    setSaveError(null);
    updateMutation.mutate(form);
  };

  const handleDelete = () => {
    if (deleteMutation.isPending || !item) return;
    if (window.confirm(t('records.confirmDelete', { title: item.title }))) {
      setDeleteError(null);
      deleteMutation.mutate();
    }
  };

  const backLink = (
    <Link to="/data" className="inline-flex items-center text-sm font-medium text-brand hover:text-brand-strong mb-4">
      ‹ {t('records.back')}
    </Link>
  );

  if (isLoading) {
    return (
      <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
        {backLink}
        <div className="text-center py-10 text-muted-foreground">{t('common.loading')}</div>
      </div>
    );
  }

  if (isError || !item) {
    return (
      <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
        {backLink}
        <div className="text-center py-10 text-muted-foreground">{t('records.notFound')}</div>
      </div>
    );
  }

  const inputClass =
    'w-full border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2 border';

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      {backLink}

      {!isEditing ? (
        <div className="bg-surface rounded-lg shadow-sm border border-border overflow-hidden">
          <div className="p-4 sm:p-6">
            <div className="flex items-start justify-between gap-3 mb-3">
              <h1 className="text-2xl font-bold text-foreground break-words">{item.title}</h1>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={startEdit}
                  className="text-sm font-medium text-brand hover:text-brand-strong hover:bg-brand/10 px-3 py-1 rounded-md transition-colors"
                >
                  {t('records.edit')}
                </button>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteMutation.isPending}
                  className="text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1 rounded-md disabled:text-muted-foreground disabled:hover:bg-transparent transition-colors"
                >
                  {deleteMutation.isPending ? t('records.deleting') : t('records.delete')}
                </button>
              </div>
            </div>

            {deleteError && (
              <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
                {deleteError}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2 mb-4">
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-surface-muted text-foreground">
                {optLabel('infoType', item.info_type)}
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-surface-muted text-foreground">
                {optLabel('priority', item.priority)}
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-surface-muted text-foreground">
                {optLabel('status', item.status)}
              </span>
            </div>

            <div className="text-sm text-muted-foreground space-x-4 mb-4">
              {item.date && <span>{t('list.dateLabel')}{item.date}</span>}
              {item.event_date && <span>{t('create.fieldEventDate')}: {item.event_date}</span>}
              {item.due_date && <span className="text-red-500 font-semibold">{t('list.dueLabel')}{item.due_date}</span>}
            </div>

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
              <div className="mt-6">
                <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('records.attachmentsHeading')}</p>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
                  {item.attachments.map((att) => (
                    <div key={att.id} className="relative group">
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
                {item.tags.split(',').map((tag) => (
                  <span key={tag} className="text-xs bg-border text-foreground px-2 py-1 rounded">#{tag.trim()}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        form && (
          <form onSubmit={handleSave} className="bg-surface rounded-lg shadow-sm border border-border p-4 sm:p-6 space-y-4">
            {saveError && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
                {saveError}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldTitle')}</label>
              <input name="title" type="text" value={form.title} onChange={handleChange} required className={inputClass} />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldType')}</label>
                <select name="info_type" value={form.info_type} onChange={handleChange} className={inputClass}>
                  {INFO_TYPES.map((v) => <option key={v} value={v}>{optLabel('infoType', v)}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldStatus')}</label>
                <select name="status" value={form.status} onChange={handleChange} className={inputClass}>
                  {STATUS_TYPES.map((v) => <option key={v} value={v}>{optLabel('status', v)}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldPriority')}</label>
                <select name="priority" value={form.priority} onChange={handleChange} className={inputClass}>
                  {PRIORITY_TYPES.map((v) => <option key={v} value={v}>{optLabel('priority', v)}</option>)}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldDate')}</label>
                <input name="date" type="date" value={form.date ?? ''} onChange={handleChange} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldEventDate')}</label>
                <input name="event_date" type="date" value={form.event_date ?? ''} onChange={handleChange} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldDueDate')}</label>
                <input name="due_date" type="date" value={form.due_date ?? ''} onChange={handleChange} className={inputClass} />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldContent')}</label>
              <textarea name="content" rows={12} value={form.content} onChange={handleChange} required className={inputClass} />
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldItems')}</label>
              <textarea name="items" rows={3} value={form.items ?? ''} onChange={handleChange} placeholder={t('create.itemsPlaceholder')} className={inputClass} />
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldTags')}</label>
              <input name="tags" type="text" value={form.tags ?? ''} onChange={handleChange} placeholder={t('create.tagsPlaceholder')} className={inputClass} />
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">{t('create.fieldMemo')}</label>
              <textarea name="memo" rows={6} value={form.memo ?? ''} onChange={handleChange} className={inputClass} />
            </div>

            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={updateMutation.isPending}
                className="bg-brand text-white font-semibold px-4 py-2 rounded-md hover:bg-brand-strong disabled:opacity-60 transition-colors"
              >
                {updateMutation.isPending ? t('common.loading') : t('records.save')}
              </button>
              <button
                type="button"
                onClick={cancelEdit}
                className="text-foreground font-medium px-4 py-2 rounded-md border border-border hover:bg-surface-muted transition-colors"
              >
                {t('records.cancel')}
              </button>
            </div>
          </form>
        )
      )}
    </div>
  );
};

const DataDetailPage: React.FC = () => {
  const params = useParams();
  const id = Number(params.id);
  // id が変わると DataDetail を再マウントし、編集状態を確実に初期化する
  return <DataDetail key={id} id={id} />;
};

export default DataDetailPage;
