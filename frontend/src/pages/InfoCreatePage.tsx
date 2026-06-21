import React, { useState, useRef, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { extractInfoDraft } from '../api';
import type { NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { useCreateFlow } from '../contexts/useCreateFlow';
import { compressImageFile, compressImageFiles } from '../utils/imageCompression';
import { INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES } from './infoFormOptions';

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

  // 写真から自動入力 (SOT-829)
  const photoInputRef = useRef<HTMLInputElement>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractNotice, setExtractNotice] = useState<string | null>(null);
  const [extractError, setExtractError] = useState<string | null>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
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

  // 写真をアップロードしてOCR・構造化し、フォームを自動入力する (SOT-829)
  const handlePhotoExtract = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // input をリセットして同じファイルでも再選択できるようにする
    if (photoInputRef.current) photoInputRef.current.value = '';
    if (!file) return;

    setIsExtracting(true);
    setExtractError(null);
    setExtractNotice(null);

    try {
      // アップロード前に圧縮・JPEG変換し、OCR・添付ともに変換後ファイルのみを使う（生データは保持しない）
      const processed = await compressImageFile(file);
      const draft = await extractInfoDraft(processed);
      setFormData(prev => ({
        ...prev,
        title: draft.title || prev.title,
        // 推定種別が選択肢に存在する場合のみ採用
        info_type: INFO_TYPES.includes(draft.info_type) ? draft.info_type : prev.info_type,
        content: draft.content || prev.content,
        items: draft.items || prev.items,
        date: draft.date || prev.date,
      }));
      // 解析した写真（変換後）を添付として保持
      setSelectedFiles(prev => (prev.includes(processed) ? prev : [...prev, processed]));
      // 写真アップ＝一時登録完了。確認ページで内容を確認して登録する。
      setExtractNotice(t('create.uploadComplete'));
    } catch (error: unknown) {
      console.error('Failed to extract from photo', error);
      let msg = t('create.extractFailDefault');
      if (axios.isAxiosError(error)) {
        if (error.response?.status === 413) {
          msg = t('create.extractFail413');
        } else if (error.response?.status === 400) {
          msg = t('create.extractFail400');
        }
      }
      setExtractError(msg);
    } finally {
      setIsExtracting(false);
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
      <h1 className="text-2xl font-bold mb-6 text-gray-800">{t('create.title')}</h1>

      <form onSubmit={handleSubmit} className="bg-white shadow-md rounded-lg p-6 space-y-4">
        {/* 写真から自動入力 (SOT-832) */}
        <div className="border border-dashed border-blue-300 bg-blue-50 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-blue-800">{t('create.photoHeading')}</h2>
          <p className="mt-1 text-xs text-gray-600">
            {t('create.photoDesc')}
          </p>
          <input
            type="file"
            accept="image/*"
            ref={photoInputRef}
            onChange={handlePhotoExtract}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => photoInputRef.current?.click()}
            disabled={isExtracting || isSubmitting}
            className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExtracting ? (
              <>
                <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {t('create.photoAnalyzing')}
              </>
            ) : (
              t('create.photoButton')
            )}
          </button>
          {extractNotice && (
            <p className="mt-2 text-sm text-green-700">{extractNotice}</p>
          )}
          {extractError && (
            <p className="mt-2 text-sm text-red-600">
              {extractError}{t('create.photoErrorSuffix')}
            </p>
          )}
        </div>

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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
          ></textarea>
        </div>

        <div
          className={`pt-4 px-2 pb-2 rounded-md transition-colors ${
            isDragging ? 'bg-blue-50 border-2 border-dashed border-blue-400' : 'border-t border-gray-200'
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('create.fieldAttachments')}
            {isDragging && <span className="ml-2 text-blue-600 font-bold">{t('create.dropHint')}</span>}
          </label>
          <input
            type="file"
            multiple
            accept="image/*,application/pdf"
            onChange={handleFileChange}
            ref={fileInputRef}
            className="block w-full text-sm text-gray-500
              file:mr-4 file:py-2 file:px-4
              file:rounded-md file:border-0
              file:text-sm file:font-semibold
              file:bg-blue-50 file:text-blue-700
              hover:file:bg-blue-100"
            disabled={isSubmitting}
          />
          <p className="mt-2 text-xs text-gray-500">{t('create.compressNote')}</p>
          {isProcessingFiles && (
            <p className="mt-2 text-sm text-blue-700">{t('create.processingFiles')}</p>
          )}
          {selectedFiles.length > 0 && (
            <>
              <p className="mt-3 mb-1 text-xs font-medium text-gray-600">{t('create.previewHeading')}</p>
              <ul className="text-sm text-gray-600 space-y-2">
                {selectedFiles.map((file, i) => (
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
            </>
          )}
        </div>

        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="mr-4 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            {t('create.cancel')}
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="px-6 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-blue-300 min-w-[120px]"
          >
            {isProcessingFiles ? t('create.processingFiles') : t('create.proceed')}
          </button>
        </div>
      </form>
    </div>
  );
};

export default InfoCreatePage;
