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
      <h1 className="text-2xl font-bold mb-2 text-gray-800">{t('draft.title')}</h1>

      <div className="mb-4 flex items-center gap-2 rounded-md bg-green-50 border border-green-200 px-4 py-3">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-green-500 text-white text-sm" aria-hidden>✓</span>
        <p className="text-sm font-medium text-green-800">{t('draft.uploadComplete')}</p>
      </div>
      <p className="mb-4 text-sm text-gray-600">{t('draft.desc')}</p>

      <form onSubmit={handleNext} className="bg-white shadow-md rounded-lg p-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700">{t('create.fieldTitle')}</label>
            <input
              type="text"
              name="title"
              required
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.title}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">{t('create.fieldType')}</label>
            <select
              name="info_type"
              required
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.info_type}
              onChange={handleChange}
            >
              {INFO_TYPES.map(v => <option key={v} value={v}>{optLabel('infoType', v)}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">{t('create.fieldStatus')}</label>
            <select
              name="status"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.status}
              onChange={handleChange}
            >
              {STATUS_TYPES.map(s => <option key={s} value={s}>{optLabel('status', s)}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">{t('create.fieldPriority')}</label>
            <select
              name="priority"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.priority}
              onChange={handleChange}
            >
              {PRIORITY_TYPES.map(p => <option key={p} value={p}>{optLabel('priority', p)}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">{t('create.fieldDate')}</label>
            <input
              type="date"
              name="date"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.date}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">{t('create.fieldEventDate')}</label>
            <input
              type="date"
              name="event_date"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.event_date}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">{t('create.fieldDueDate')}</label>
            <input
              type="date"
              name="due_date"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.due_date}
              onChange={handleChange}
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">{t('create.fieldContent')}</label>
          <textarea
            name="content"
            required
            rows={4}
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            value={formData.content}
            onChange={handleChange}
          ></textarea>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">{t('create.fieldItems')}</label>
          <input
            type="text"
            name="items"
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            placeholder={t('create.itemsPlaceholder')}
            value={formData.items}
            onChange={handleChange}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">{t('create.fieldTags')}</label>
          <input
            type="text"
            name="tags"
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            placeholder={t('create.tagsPlaceholder')}
            value={formData.tags}
            onChange={handleChange}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">{t('create.fieldMemo')}</label>
          <textarea
            name="memo"
            rows={2}
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            value={formData.memo}
            onChange={handleChange}
          ></textarea>
        </div>

        {files.length > 0 && (
          <div className="border-t border-gray-200 pt-4">
            <p className="mb-2 text-sm font-medium text-gray-700">{t('draft.attachments')}</p>
            <ul className="text-sm text-gray-600 space-y-2">
              {files.map((file, i) => (
                <li key={i} className="flex items-center gap-3">
                  {previewUrls[i] ? (
                    <img
                      src={previewUrls[i] as string}
                      alt={file.name}
                      className="h-14 w-14 object-cover rounded border border-gray-200 flex-shrink-0"
                    />
                  ) : (
                    <span className="h-14 w-14 flex items-center justify-center rounded border border-gray-200 bg-gray-50 text-gray-400 text-xs flex-shrink-0">
                      PDF
                    </span>
                  )}
                  <span className="min-w-0">
                    <span className="block truncate max-w-xs">{file.name}</span>
                    <span className="text-gray-400">({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
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
            className="mr-4 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            {t('draft.back')}
          </button>
          <button
            type="submit"
            className="px-6 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 min-w-[120px]"
          >
            {t('draft.next')}
          </button>
        </div>
      </form>
    </div>
  );
};

export default DraftConfirmPage;
