import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { suggestInfoTags } from '../api';
import type { NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { useCreateFlow } from '../contexts/useCreateFlow';
import { compressImageFiles } from '../utils/imageCompression';
import { INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES } from './infoFormOptions';
import RegisterMenu from '../components/RegisterMenu';

const InfoCreatePage: React.FC = () => {
  const { t } = useI18n();
  // 表示専用ラベル: 保存値（日本語）は変えず、表示テキストのみ翻訳する
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };
  const navigate = useNavigate();
  const { staged, setStaged } = useCreateFlow();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [formData, setFormData] = useState<NurseryInfoCreate>(() => staged?.data ?? {
    title: '',
    info_type: '資料',
    content: '',
    date: '',
    event_date: '',
    due_date: '',
    items: '',
    status: '未対応',
    priority: '普通',
    tags: '',
    memo: '',
  });

  const [selectedFiles, setSelectedFiles] = useState<File[]>(staged?.files ?? []);
  // プレビュー用 object URL（画像のみ）。selectedFiles に同期して生成/破棄する。
  const [isProcessingFiles, setIsProcessingFiles] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // 登録時AI自動タグ付け (SOT-1039 / 提案3)
  const [isTagging, setIsTagging] = useState(false);
  const [tagNotice, setTagNotice] = useState<string | null>(null);
  const [tagError, setTagError] = useState<string | null>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  // タイトル・内容・持ち物からAIで種別/優先度/日付/タグを推定し、フォームへ反映する（編集可能）
  const handleAutoTag = async () => {
    setTagError(null);
    setTagNotice(null);
    if (!formData.title?.trim() && !formData.content?.trim()) {
      setTagError(t('create.aiTagNeedInput'));
      return;
    }
    setIsTagging(true);
    try {
      const s = await suggestInfoTags({
        title: formData.title || '',
        content: formData.content || '',
        items: formData.items || undefined,
        info_type: formData.info_type || undefined,
      });
      setFormData(prev => ({
        ...prev,
        info_type: INFO_TYPES.includes(s.info_type) ? s.info_type : prev.info_type,
        priority: PRIORITY_TYPES.includes(s.priority) ? s.priority : prev.priority,
        date: s.date || prev.date,
        due_date: s.due_date || prev.due_date,
        event_date: s.event_date || prev.event_date,
        tags: s.tags && s.tags.length > 0 ? s.tags.join(', ') : prev.tags,
      }));
      setTagNotice(t('create.aiTagDone'));
    } catch (error) {
      console.error('Failed to auto-tag', error);
      setTagError(t('create.aiTagFail'));
    } finally {
      setIsTagging(false);
    }
  };

  const previewUrls = useMemo(
    () => selectedFiles.map((file) =>
      file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
    ),
    [selectedFiles],
  );

  // selectedFiles の変更に追従して作成したプレビュー用 URL を不要になったら破棄する
  useEffect(() => () => {
    previewUrls.forEach((url) => url && URL.revokeObjectURL(url));
  }, [previewUrls]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const picked = Array.from(e.target.files);
    // 同じファイルでも再選択できるよう input をリセット
    if (fileInputRef.current) fileInputRef.current.value = '';
    setIsProcessingFiles(true);
    try {
      // アップロード前に画像を圧縮・JPEG変換（生データは保持しない）
      const processed = await compressImageFiles(picked);
      setSelectedFiles(processed);
    } finally {
      setIsProcessingFiles(false);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isSubmitting) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (isSubmitting) return;

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const files = Array.from(e.dataTransfer.files);
      const acceptedFiles = files.filter(file =>
        file.type.startsWith('image/') || file.type === 'application/pdf'
      );

      if (acceptedFiles.length > 0) {
        setIsProcessingFiles(true);
        try {
          // アップロード前に画像を圧縮・JPEG変換（生データは保持しない）
          const processed = await compressImageFiles(acceptedFiles);
          setSelectedFiles(prev => [...prev, ...processed]);
        } finally {
          setIsProcessingFiles(false);
        }
      }
    }
  };

  // 入力内容を一時保持し、一時登録確認ページへ進む（本登録はまだ行わない）
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setStaged({ data: formData, files: selectedFiles });
    navigate('/create/confirm-draft');
  };

  const isSubmitting = isProcessingFiles;

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <RegisterMenu />
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('create.manualTitle')}</h1>

      <form onSubmit={handleSubmit} className="bg-surface shadow-md rounded-lg p-6 space-y-4">
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
          ></textarea>
        </div>

        <div
          className={`pt-4 px-2 pb-2 rounded-md transition-colors ${
            isDragging ? 'bg-brand-soft border-2 border-dashed border-brand' : 'border-t border-border'
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <label className="block text-sm font-medium text-foreground mb-2">
            {t('create.fieldAttachments')}
            {isDragging && <span className="ml-2 text-brand font-bold">{t('create.dropHint')}</span>}
          </label>
          <input
            type="file"
            multiple
            accept="image/*,application/pdf"
            onChange={handleFileChange}
            ref={fileInputRef}
            className="block w-full text-sm text-muted-foreground
              file:mr-4 file:py-2 file:px-4
              file:rounded-md file:border-0
              file:text-sm file:font-semibold
              file:bg-brand-soft file:text-brand-strong
              hover:file:bg-brand-soft"
            disabled={isSubmitting}
          />
          <p className="mt-2 text-xs text-muted-foreground">{t('create.compressNote')}</p>
          {isProcessingFiles && (
            <p className="mt-2 text-sm text-brand-strong">{t('create.processingFiles')}</p>
          )}
          {selectedFiles.length > 0 && (
            <>
              <p className="mt-3 mb-1 text-xs font-medium text-muted-foreground">{t('create.previewHeading')}</p>
              <ul className="text-sm text-muted-foreground space-y-2">
                {selectedFiles.map((file, i) => (
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
            </>
          )}
        </div>

        {/* 登録時AI自動タグ付け (SOT-1039 / 提案3) */}
        <div className="border border-dashed border-emerald-200 bg-emerald-50/40 rounded-md p-3">
          <h2 className="text-xs font-medium text-emerald-800">{t('create.aiTagHeading')}</h2>
          <p className="mt-1 text-[11px] text-muted-foreground">{t('create.aiTagDesc')}</p>
          <button
            type="button"
            onClick={handleAutoTag}
            disabled={isTagging || isSubmitting}
            className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white text-xs font-medium rounded-md shadow-sm hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isTagging ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {t('create.aiTagAnalyzing')}
              </>
            ) : (
              t('create.aiTagButton')
            )}
          </button>
          {tagNotice && <p className="mt-2 text-xs text-emerald-700">{tagNotice}</p>}
          {tagError && <p className="mt-2 text-xs text-red-600">{tagError}</p>}
        </div>

        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="mr-4 px-4 py-2 text-sm font-medium text-foreground bg-surface border border-border rounded-md hover:bg-surface-muted"
          >
            {t('create.cancel')}
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="px-6 py-2 text-sm font-medium text-white bg-brand rounded-md hover:bg-brand-strong disabled:bg-brand min-w-[120px]"
          >
            {isProcessingFiles ? t('create.processingFiles') : t('create.proceed')}
          </button>
        </div>
      </form>
    </div>
  );
};

export default InfoCreatePage;
