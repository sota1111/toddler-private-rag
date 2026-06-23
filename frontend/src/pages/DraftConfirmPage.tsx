import React, { useState, useEffect, useMemo } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import type { NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { useCreateFlow } from '../contexts/useCreateFlow';
import { INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES } from './infoFormOptions';

const EMPTY_FILES: File[] = [];

// 一時登録確認ページ (SOT-1010): 写真アップ/手入力した内容を「アップ完了（一時登録）」として表示し、
// 確認・修正できるようにする。本登録はまだ行わない。
const DraftConfirmPage: React.FC = () => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { staged, setStaged } = useCreateFlow();

  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const [formData, setFormData] = useState<NurseryInfoCreate>(
    staged?.data ?? {
      title: '', info_type: '資料', content: '', date: '', event_date: '',
      due_date: '', items: '', status: '未対応', priority: '普通', tags: '', memo: '',
    },
  );

  const files = staged?.files ?? EMPTY_FILES;
  const previewUrls = useMemo(
    () => files.map((file) => (file.type.startsWith('image/') ? URL.createObjectURL(file) : null)),
    [files],
  );
  useEffect(() => () => {
    previewUrls.forEach((url) => url && URL.revokeObjectURL(url));
  }, [previewUrls]);

  // 一時保持された入力が無ければ登録ページへ戻す
  if (!staged) {
    return <Navigate to="/create" replace />;
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleNext = (e: React.FormEvent) => {
    e.preventDefault();
    setStaged({ data: formData, files });
    navigate('/create/confirm-register');
  };

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-2 text-foreground">{t('draft.title')}</h1>

      <div className="mb-4 flex items-center gap-2 rounded-md bg-green-50 border border-green-200 px-4 py-3">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-green-500 text-white text-sm" aria-hidden>✓</span>
        <p className="text-sm font-medium text-green-800">{t('draft.uploadComplete')}</p>
      </div>
      <p className="mb-4 text-sm text-muted-foreground">{t('draft.desc')}</p>

      <form onSubmit={handleNext} className="bg-surface shadow-md rounded-lg p-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-foreground">{t('create.fieldTitle')}</label>
            <input
              type="text"
              name="title"
              required
              className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
              value={formData.title}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground">{t('create.fieldType')}</label>
            <select
              name="info_type"
              required
              className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
              value={formData.info_type}
              onChange={handleChange}
            >
              {INFO_TYPES.map(v => <option key={v} value={v}>{optLabel('infoType', v)}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground">{t('create.fieldStatus')}</label>
            <select
              name="status"
              className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
              value={formData.status}
              onChange={handleChange}
            >
              {STATUS_TYPES.map(s => <option key={s} value={s}>{optLabel('status', s)}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground">{t('create.fieldPriority')}</label>
            <select
              name="priority"
              className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
              value={formData.priority}
              onChange={handleChange}
            >
              {PRIORITY_TYPES.map(p => <option key={p} value={p}>{optLabel('priority', p)}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground">{t('create.fieldDate')}</label>
            <input
              type="date"
              name="date"
              className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
              value={formData.date}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground">{t('create.fieldEventDate')}</label>
            <input
              type="date"
              name="event_date"
              className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
              value={formData.event_date}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground">{t('create.fieldDueDate')}</label>
            <input
              type="date"
              name="due_date"
              className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
              value={formData.due_date}
              onChange={handleChange}
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground">{t('create.fieldContent')}</label>
          <textarea
            name="content"
            required
            rows={4}
            className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
            value={formData.content}
            onChange={handleChange}
          ></textarea>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground">{t('create.fieldItems')}</label>
          <input
            type="text"
            name="items"
            className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
            placeholder={t('create.itemsPlaceholder')}
            value={formData.items}
            onChange={handleChange}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground">{t('create.fieldTags')}</label>
          <input
            type="text"
            name="tags"
            className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
            placeholder={t('create.tagsPlaceholder')}
            value={formData.tags}
            onChange={handleChange}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground">{t('create.fieldMemo')}</label>
          <textarea
            name="memo"
            rows={2}
            className="mt-1 block w-full border border-border rounded-md shadow-sm p-2"
            value={formData.memo}
            onChange={handleChange}
          ></textarea>
        </div>

        {files.length > 0 && (
          <div className="border-t border-border pt-4">
            <p className="mb-2 text-sm font-medium text-foreground">{t('draft.attachments')}</p>
            <ul className="text-sm text-muted-foreground space-y-2">
              {files.map((file, i) => (
                <li key={i} className="flex items-center gap-3">
                  {previewUrls[i] ? (
                    <img
                      src={previewUrls[i] as string}
                      alt={file.name}
                      className="h-14 w-14 object-cover rounded border border-border flex-shrink-0"
                    />
                  ) : (
                    <span className="h-14 w-14 flex items-center justify-center rounded border border-border bg-surface-muted text-muted-foreground text-xs flex-shrink-0">
                      PDF
                    </span>
                  )}
                  <span className="min-w-0">
                    <span className="block truncate max-w-xs">{file.name}</span>
                    <span className="text-muted-foreground">({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={() => navigate('/create')}
            className="mr-4 px-4 py-2 text-sm font-medium text-foreground bg-surface border border-border rounded-md hover:bg-surface-muted"
          >
            {t('draft.back')}
          </button>
          <button
            type="submit"
            className="px-6 py-2 text-sm font-medium text-white bg-brand rounded-md hover:bg-brand-strong min-w-[120px]"
          >
            {t('draft.next')}
          </button>
        </div>
      </form>
    </div>
  );
};

export default DraftConfirmPage;
