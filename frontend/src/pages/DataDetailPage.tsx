import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { getInfoById, deleteInfo, getAttachmentFileUrl, getAttachmentTranscription } from '../api';
import type { Attachment } from '../types';
import { useI18n } from '../i18n/useI18n';

// SOT-1325: 写真を大きく表示し、その下に文字起こし(OCR原文)を設定言語で表示する。
// 画像ごとに独立した文字起こしクエリを持たせるため子コンポーネントに切り出す。
const AttachmentBlock: React.FC<{ att: Attachment }> = ({ att }) => {
  const { t, lang } = useI18n();
  const isImage = att.mime_type.startsWith('image/');

  const { data, isLoading } = useQuery({
    queryKey: ['attachment-transcription', att.id, lang],
    queryFn: () => getAttachmentTranscription(att.id, lang),
    enabled: isImage,
  });

  if (!isImage) {
    return (
      <a
        href={getAttachmentFileUrl(att.id)}
        target="_blank"
        rel="noopener noreferrer"
        className="flex flex-col items-center justify-center bg-surface rounded-md border border-border p-4 hover:bg-surface-muted transition-colors"
      >
        <svg className="w-8 h-8 text-muted-foreground mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
        </svg>
        <span className="text-xs text-muted-foreground text-center break-all px-1">
          {att.original_filename}
        </span>
      </a>
    );
  }

  const text = data?.text ?? '';

  return (
    <div className="space-y-3">
      <img
        src={getAttachmentFileUrl(att.id)}
        alt={att.original_filename}
        className="w-full h-auto max-h-[70vh] object-contain rounded-md border border-border bg-border cursor-pointer hover:opacity-95 transition-opacity"
        loading="lazy"
        onClick={() => window.open(getAttachmentFileUrl(att.id), '_blank')}
      />
      <div>
        <h2 className="text-sm font-semibold text-muted-foreground mb-1">{t('records.transcription')}</h2>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('records.transcriptionLoading')}</p>
        ) : text.trim() ? (
          <p className="whitespace-pre-wrap break-words text-foreground">{text}</p>
        ) : (
          <p className="text-sm text-muted-foreground">{t('records.transcriptionEmpty')}</p>
        )}
      </div>
    </div>
  );
};

// SOT-1309: データ一覧の詳細ページ。タイトルと写真（添付）のみを表示し、削除できる。
// 編集・ステータス変更などは廃止し、表示と削除に役割を絞った。
// id ごとに key 付きで再マウントすることで、別レコードへ遷移したときに状態を確実にリセットする。
const DataDetail: React.FC<{ id: string }> = ({ id }) => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data: item, isLoading, isError } = useQuery({
    queryKey: ['info-detail', id],
    queryFn: () => getInfoById(id),
    enabled: Boolean(id),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteInfo(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
      navigate(-1);
    },
    onError: () => setDeleteError(t('records.deleteError')),
  });

  const handleDelete = () => {
    if (deleteMutation.isPending || !item) return;
    if (window.confirm(t('records.confirmDelete', { title: item.title }))) {
      setDeleteError(null);
      deleteMutation.mutate();
    }
  };

  const backLink = (
    <button
      type="button"
      onClick={() => navigate(-1)}
      className="inline-flex items-center text-sm font-medium text-brand hover:text-brand-strong mb-4"
    >
      ‹ {t('records.back')}
    </button>
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

  // SOT-1331: 写真一覧から開く写真ありレコードは「写真＋文字起こしのみ」を表示し、
  // 写真の上のタイトル・日付・ステータス・本文(content)は出さない。
  // 一方で /tasks から開く写真なしのタスクレコードは、SOT-1313 どおりタイトル等を表示する
  // （この詳細画面はタスク一覧と写真一覧で共有されているため）。
  const hasPhoto = Boolean(item.attachments && item.attachments.length > 0);

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      {backLink}

      <div className="bg-surface rounded-lg shadow-sm border border-border overflow-hidden">
        <div className="p-4 sm:p-6">
          <div className={`flex items-start gap-3 mb-4 ${hasPhoto ? 'justify-end' : 'justify-between'}`}>
            {!hasPhoto && (
              <h1 className="text-2xl font-bold text-foreground break-words">{item.title}</h1>
            )}
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1 rounded-md disabled:text-muted-foreground disabled:hover:bg-transparent transition-colors flex-shrink-0"
            >
              {deleteMutation.isPending ? t('records.deleting') : t('records.delete')}
            </button>
          </div>

          {deleteError && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
              {deleteError}
            </div>
          )}

          {/* SOT-1313: タスク等の詳細を確認できるよう、日付・ステータス・内容を値があるときのみ表示する。
              SOT-1331: 写真ありレコードはこれらを出さず、写真＋文字起こしのみにする。 */}
          {!hasPhoto && item.event_date && (
            <div className="mb-3">
              <span className="inline-flex items-center gap-1 text-sm font-medium bg-emerald-100 text-emerald-800 px-3 py-1 rounded-full">
                📅 {t('records.eventDate')}: {item.event_date}
              </span>
            </div>
          )}

          {!hasPhoto && item.status && (
            <div className="mb-3 text-sm text-muted-foreground">
              {t('records.status')}: <span className="font-medium text-foreground">{item.status}</span>
            </div>
          )}

          {!hasPhoto && item.content && (
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-1">{t('records.content')}</h2>
              <p className="whitespace-pre-wrap break-words text-foreground">{item.content}</p>
            </div>
          )}

          {/* SOT-1325: 写真を大きく表示し、その下に文字起こし(OCR原文)を設定言語で表示する。 */}
          {item.attachments && item.attachments.length > 0 && (
            <div className="space-y-6">
              {item.attachments.map((att) => (
                <AttachmentBlock key={att.id} att={att} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const DataDetailPage: React.FC = () => {
  const params = useParams();
  // SOT-1284: Firestore 移行後 id は文字列のため、Number() で NaN 化せず文字列のまま扱う
  const id = params.id ?? '';
  // id が変わると DataDetail を再マウントし、状態を確実に初期化する
  return <DataDetail key={id} id={id} />;
};

export default DataDetailPage;
