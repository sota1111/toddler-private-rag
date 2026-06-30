import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { getInfoById, deleteInfo, updateInfo, getAttachmentFileUrl, getAttachmentTranscription, investigateDeadline } from '../api';
import type { Attachment } from '../types';
import { STATUS_TYPES } from './infoFormOptions';
import { useI18n } from '../i18n/useI18n';
import { useConfirm } from '../components/confirmDialogContext';
import { useSettings } from '../settings/useSettings';

// SOT-1404: 本文中の http(s) URL（締切調査の「根拠となる出典リンク」など）をクリック可能な
// リンクに変換して表示する。URL 以外のテキストはそのまま（改行は whitespace-pre-wrap で維持）。
const URL_SPLIT_REGEX = /(https?:\/\/[^\s]+)/g;
const URL_TEST_REGEX = /^https?:\/\/[^\s]+$/;

const LinkifiedText: React.FC<{ text: string; className?: string }> = ({ text, className }) => {
  const parts = text.split(URL_SPLIT_REGEX);
  return (
    <p className={className}>
      {parts.map((part, i) => {
        if (URL_TEST_REGEX.test(part)) {
          // 末尾の句読点はリンクに含めない（日本語本文対策）。
          const match = part.match(/^(.*?)([、。）)]*)$/s);
          const url = match ? match[1] : part;
          const trail = match ? match[2] : '';
          return (
            <React.Fragment key={i}>
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline break-all"
              >
                {url}
              </a>
              {trail}
            </React.Fragment>
          );
        }
        return <React.Fragment key={i}>{part}</React.Fragment>;
      })}
    </p>
  );
};

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
          <LinkifiedText text={text} className="whitespace-pre-wrap break-words text-foreground" />
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
  const confirm = useConfirm();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // SOT-1405: 締切調査に設定の市町村を渡す（DLページリンク生成に使う）。
  const { municipality } = useSettings();

  // 種別/ステータスのラベルは保存値（日本語）のまま、表示は設定言語に合わせて翻訳する。
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const { data: item, isLoading, isError } = useQuery({
    queryKey: ['info-detail', id],
    queryFn: () => getInfoById(id),
    enabled: Boolean(id),
  });

  // SOT-1337: 一覧から開いた項目のステータスだけを、編集モードに入らず即時変更する。
  const statusMutation = useMutation({
    mutationFn: (status: string) => updateInfo(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info-detail', id] });
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
    },
    onError: () => setStatusError(t('records.statusError')),
  });

  const handleStatusChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value;
    if (!item || next === item.status || statusMutation.isPending) return;
    setStatusError(null);
    statusMutation.mutate(next);
  };

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

  // SOT-1369: 締め切り調査。一覧から選んだ項目に対し、提出書類先回りエージェントを手動起動する。
  const [investigateMessage, setInvestigateMessage] = useState<string | null>(null);
  const [investigateError, setInvestigateError] = useState<string | null>(null);
  const investigateMutation = useMutation({
    mutationFn: () => investigateDeadline(id, municipality),
    onSuccess: (res) => {
      setInvestigateError(null);
      setInvestigateMessage(
        res.created > 0
          ? t('records.investigateDone', { count: String(res.created) })
          : t('records.investigateNone'),
      );
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
    },
    onError: () => {
      setInvestigateMessage(null);
      setInvestigateError(t('records.investigateError'));
    },
  });

  const handleInvestigate = () => {
    if (investigateMutation.isPending) return;
    setInvestigateMessage(null);
    setInvestigateError(null);
    investigateMutation.mutate();
  };

  const handleDelete = async () => {
    if (deleteMutation.isPending || !item) return;
    if (await confirm(t('records.confirmDelete', { title: item.title }))) {
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

          {/* SOT-1369: 締め切り調査を手動トリガするボタン。写真あり/なし両方で表示する。
              SOT-1407: 期限の調査が必要なタスク(needs_deadline_investigation=true)のみ表示する。 */}
          {item.needs_deadline_investigation && (
            <div className="mb-4">
              <button
                type="button"
                onClick={handleInvestigate}
                disabled={investigateMutation.isPending}
                className="text-sm font-medium text-brand-strong border border-accent-border bg-accent-bg hover:opacity-90 px-3 py-1.5 rounded-md disabled:opacity-60 transition-colors"
              >
                {investigateMutation.isPending ? t('records.investigating') : t('records.investigate')}
              </button>
              {investigateMessage && (
                <div className="mt-2 p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm">
                  {investigateMessage}
                </div>
              )}
              {investigateError && (
                <div className="mt-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
                  {investigateError}
                </div>
              )}
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

          {/* SOT-1337: 読み取り専用表示をやめ、一覧から開いた項目のステータスを即時変更できるようにする。
              写真ありレコードは hasPhoto ゲートで対象外（SOT-1331: 写真＋文字起こしのみ）。 */}
          {!hasPhoto && item.status && (
            <div className="mb-4">
              <div className="flex items-center gap-2">
                <label htmlFor="status-change" className="text-sm font-medium text-foreground">
                  {t('records.changeStatus')}
                </label>
                <select
                  id="status-change"
                  value={item.status}
                  onChange={handleStatusChange}
                  disabled={statusMutation.isPending}
                  className="border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2 border disabled:opacity-60"
                >
                  {STATUS_TYPES.map((v) => <option key={v} value={v}>{optLabel('status', v)}</option>)}
                </select>
              </div>
              {statusError && (
                <div className="mt-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
                  {statusError}
                </div>
              )}
            </div>
          )}

          {!hasPhoto && item.content && (
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-1">{t('records.content')}</h2>
              <LinkifiedText text={item.content} className="whitespace-pre-wrap break-words text-foreground" />
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
