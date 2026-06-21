import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { Navigate, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { createInfo, uploadAttachment } from '../api';
import { useI18n } from '../i18n/useI18n';
import { useCreateFlow } from '../contexts/useCreateFlow';

const EMPTY_FILES: File[] = [];

// 登録情報確認ページ (SOT-1010): 登録する内容を読み取り専用で最終確認し、「登録する」で本登録する。
const RegisterConfirmPage: React.FC = () => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { staged, clear } = useCreateFlow();

  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState({ current: 0, total: 0 });
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const files = staged?.files ?? EMPTY_FILES;
  const previewUrls = useMemo(
    () => files.map((file) => (file.type.startsWith('image/') ? URL.createObjectURL(file) : null)),
    [files],
  );
  useEffect(() => () => {
    previewUrls.forEach((url) => url && URL.revokeObjectURL(url));
  }, [previewUrls]);

  if (!staged) {
    return <Navigate to="/create" replace />;
  }

  const data = staged.data;

  const fields: { label: string; value?: string; group?: string }[] = [
    { label: t('create.fieldTitle'), value: data.title },
    { label: t('create.fieldType'), value: data.info_type, group: 'infoType' },
    { label: t('create.fieldStatus'), value: data.status, group: 'status' },
    { label: t('create.fieldPriority'), value: data.priority, group: 'priority' },
    { label: t('create.fieldDate'), value: data.date },
    { label: t('create.fieldEventDate'), value: data.event_date },
    { label: t('create.fieldDueDate'), value: data.due_date },
    { label: t('create.fieldContent'), value: data.content },
    { label: t('create.fieldItems'), value: data.items },
    { label: t('create.fieldTags'), value: data.tags },
    { label: t('create.fieldMemo'), value: data.memo },
  ];

  const handleRegister = async () => {
    setErrorMessage(null);
    setIsSubmitting(true);
    try {
      const newInfo = await createInfo(data);

      if (files.length > 0) {
        setUploadProgress({ current: 0, total: files.length });
        const failedFiles: string[] = [];

        for (let i = 0; i < files.length; i++) {
          setUploadProgress({ current: i + 1, total: files.length });
          try {
            await uploadAttachment(newInfo.id, files[i]);
          } catch (error: unknown) {
            console.error(`Failed to upload ${files[i].name}`, error);
            let msg = files[i].name;
            if (axios.isAxiosError(error)) {
              if (error.response?.status === 413) {
                msg += ` ${t('create.uploadErr413')}`;
              } else if (error.response?.status === 400) {
                msg += ` ${t('create.uploadErr400')}`;
              } else {
                msg += ` ${t('create.uploadErrGeneric')}`;
              }
            } else {
              msg += ` ${t('create.uploadErrGeneric')}`;
            }
            failedFiles.push(msg);
          }
        }

        if (failedFiles.length > 0) {
          // 本体は登録済み。添付の一部失敗のみ通知し、一覧で確認してもらう。
          setErrorMessage(`${t('create.uploadPartialFail')}\n${failedFiles.join('\n')}`);
          queryClient.invalidateQueries({ queryKey: ['info'] });
          setIsSubmitting(false);
          return;
        }
      }

      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
      clear();
      navigate('/list');
    } catch (error: unknown) {
      console.error('Failed to register info', error);
      setErrorMessage(t('create.genericError'));
      setIsSubmitting(false);
    }
  };

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-2 text-gray-800">{t('confirm.title')}</h1>
      <p className="mb-4 text-sm text-gray-600">{t('confirm.desc')}</p>

      <div className="bg-white shadow-md rounded-lg p-6 space-y-4">
        <dl className="divide-y divide-gray-100">
          {fields.map((f, i) => (
            <div key={i} className="py-2 grid grid-cols-1 md:grid-cols-3 gap-1">
              <dt className="text-sm font-medium text-gray-500">{f.label}</dt>
              <dd className="md:col-span-2 text-sm text-gray-900 whitespace-pre-wrap break-words">
                {f.value ? (f.group ? optLabel(f.group, f.value) : f.value) : '—'}
              </dd>
            </div>
          ))}
        </dl>

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

        <div className="flex justify-end pt-4 border-t border-gray-200">
          <button
            type="button"
            onClick={() => navigate('/create/confirm-draft')}
            disabled={isSubmitting}
            className="mr-4 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
          >
            {t('confirm.edit')}
          </button>
          <button
            type="button"
            onClick={handleRegister}
            disabled={isSubmitting}
            className="px-6 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-blue-300 min-w-[120px]"
          >
            {isSubmitting
              ? (uploadProgress.total > 0
                  ? t('create.uploading', { current: uploadProgress.current, total: uploadProgress.total })
                  : t('confirm.submitting'))
              : t('confirm.submit')}
          </button>
        </div>

        {errorMessage && (
          <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-600 whitespace-pre-wrap">{errorMessage}</p>
            <button
              type="button"
              onClick={() => { clear(); navigate('/list'); }}
              className="mt-2 text-sm text-blue-600 font-medium hover:underline"
            >
              {t('create.backToList')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default RegisterConfirmPage;
