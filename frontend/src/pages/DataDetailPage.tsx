import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { getInfoById, deleteInfo, updateInfo, getAttachmentFileUrl, getAttachmentTranscription, rescheduleDeadline, getInfoList, revertSplitRegistered } from '../api';
import type { Attachment, NurseryInfo } from '../types';
import { STATUS_TYPES } from './infoFormOptions';
import { countAgentSplitTasks } from '../utils/splitTasks';
import { useI18n } from '../i18n/useI18n';
import { useConfirm } from '../components/confirmDialogContext';

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

// SOT-1468: 登録日時(created_at)から「登録月」入力(<input type="month">)用の YYYY-MM を作る。
// 一覧の月グルーピング(RegisteredListPage の monthKey)と同じくローカル時刻の年月を使う。
const toMonthInput = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

// SOT-1468: 選択した YYYY-MM を created_at に反映する。日・時刻は元の値を維持し、
// 対象月の末日を超える日はクランプする（例: 1/31 → 2月選択で 2/28）。戻り値は送信用 ISO 文字列。
const applyMonthToCreatedAt = (iso: string, ym: string): string | null => {
  const m = ym.match(/^(\d{4})-(\d{2})$/);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]); // 1-12
  const base = new Date(iso);
  const src = Number.isNaN(base.getTime()) ? new Date() : base;
  const daysInTarget = new Date(year, month, 0).getDate();
  const day = Math.min(src.getDate(), daysInTarget);
  const next = new Date(src);
  next.setFullYear(year, month - 1, day);
  return next.toISOString();
};

// SOT-1309: データ一覧の詳細ページ。タイトルと写真（添付）のみを表示し、削除できる。
// 編集・ステータス変更などは廃止し、表示と削除に役割を絞った。
// id ごとに key 付きで再マウントすることで、別レコードへ遷移したときに状態を確実にリセットする。
const DataDetail: React.FC<{ id: string }> = ({ id }) => {
  const { t } = useI18n();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // 種別/ステータスのラベルは保存値（日本語）のまま、表示は設定言語に合わせて翻訳する。
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  // SOT-1415: 詳細画面の編集モード。日付(event_date)・内容(content)・タイトルを変更できる。
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editError, setEditError] = useState<string | null>(null);
  // SOT-1411: 締切基準日の入力値。null のあいだは保存済みの基準日を表示する。
  const [baseDateInput, setBaseDateInput] = useState<string | null>(null);
  const [rescheduleMessage, setRescheduleMessage] = useState<string | null>(null);
  const [rescheduleError, setRescheduleError] = useState<string | null>(null);
  // SOT-1468: 写真詳細画面で「登録月」(created_at)を変更する入力値・結果表示。
  const [monthInput, setMonthInput] = useState<string | null>(null);
  const [monthMessage, setMonthMessage] = useState<string | null>(null);
  const [monthError, setMonthError] = useState<string | null>(null);

  const { data: item, isLoading, isError } = useQuery({
    queryKey: ['info-detail', id],
    queryFn: () => getInfoById(id),
    enabled: Boolean(id),
  });

  // SOT-1562: このタスクの基になった登録写真レコードのタイトルを取得する。写真の文字起こしから
  // 分解生成されたタスク(および締切調査の付随タスク)にのみ source_info_id が付く。手動追加/既存
  // タスクは未設定なので取得しない（enabled ゲート）。取得結果はタスク詳細でアーカイブの左に
  // リンク表示し、クリックで元写真の詳細へ遷移させる（後段の JSX）。
  const sourceInfoId =
    item?.source_info_id != null && String(item.source_info_id) !== ''
      ? String(item.source_info_id)
      : '';
  const { data: sourceInfo } = useQuery({
    queryKey: ['info-detail', sourceInfoId],
    queryFn: () => getInfoById(sourceInfoId),
    enabled: Boolean(sourceInfoId),
  });

  // SOT-1577 / SOT-1584: 本登録後のタスク詳細でも「分割前のタスクに戻す」導線を出す。仮登録画面と
  // 同じく、エージェントが (1/4) のように2件以上へ分割した本登録タスクがある場合のみ表示する。
  // 兄弟件数は本登録一覧(RegisteredListPage と同じ queryKey)から数え、キャッシュを共有する。
  const { data: registeredList } = useQuery({
    queryKey: ['info', 'registered'],
    queryFn: () => getInfoList(),
    enabled: Boolean(sourceInfoId),
  });
  // SOT-1584: (n/N) 分割マーカーを持つエージェント分割タスクだけを数える（1枚→複数の独立タスクや
  // 実タスク1件ではマーカーが無く 0 件となり、ボタンは表示されない）。
  const splitSiblingCount = countAgentSplitTasks(
    (registeredList ?? []) as NurseryInfo[],
    sourceInfoId,
  );
  const isSplitGroup = sourceInfoId !== '' && splitSiblingCount >= 2;

  // SOT-1577: 押下でこのタスクを含む分割グループを未分割の1タスクへまとめ直す。まとめ直すと
  // 現在のタスクは削除されるため、生成された未分割タスクの詳細へ遷移する。
  const revertSplitMutation = useMutation({
    mutationFn: () => revertSplitRegistered(sourceInfoId),
    onSuccess: (merged) => {
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
      const nextId = merged?.id != null ? String(merged.id) : '';
      navigate(nextId ? `/data/${nextId}` : '/registered');
    },
    onError: () => setDeleteError(t('drafts.actionFail')),
  });

  const handleRevertSplit = async () => {
    if (revertSplitMutation.isPending || !sourceInfoId) return;
    if (!(await confirm(t('drafts.confirmRevertSplit')))) return;
    setDeleteError(null);
    revertSplitMutation.mutate();
  };

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

  // SOT-1415: 編集モードで変更したタイトル・内容・日付を保存する。
  // 既存の更新API (PUT /info/{id}) をそのまま再利用する（バックエンド変更なし）。
  const editMutation = useMutation({
    mutationFn: () =>
      updateInfo(id, { title: editTitle, content: editContent, event_date: editDate }),
    onSuccess: () => {
      setEditError(null);
      setIsEditing(false);
      queryClient.invalidateQueries({ queryKey: ['info-detail', id] });
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
    },
    onError: () => setEditError(t('records.saveError')),
  });

  const handleStartEdit = () => {
    if (!item) return;
    setEditTitle(item.title ?? '');
    setEditContent(item.content ?? '');
    setEditDate(item.event_date ?? '');
    setEditError(null);
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setEditError(null);
    setIsEditing(false);
  };

  const handleSaveEdit = () => {
    if (editMutation.isPending) return;
    setEditError(null);
    editMutation.mutate();
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

  // SOT-1500: この項目のアーカイブ状態を切り替える。アーカイブ時はアクティブな一覧(やること
  // リスト等)から外し、アーカイブ一覧のみに表示する。再オープン対応で、アーカイブ済みの項目
  // (アーカイブ画面から開いた場合)は「アーカイブから戻す」(is_archived=false)に切り替える。
  // いずれも既存の更新API(PUT /info/{id})を is_archived で再利用する。
  const archiveMutation = useMutation({
    mutationFn: (archived: boolean) => updateInfo(id, { is_archived: archived }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['archived'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
      navigate(-1);
    },
    onError: () =>
      setDeleteError(t(item?.is_archived ? 'records.unarchiveError' : 'records.archiveError')),
  });

  const handleArchive = async () => {
    if (archiveMutation.isPending || !item) return;
    const archived = !item.is_archived;
    const message = archived
      ? t('records.confirmArchive', { title: item.title })
      : t('records.confirmUnarchive', { title: item.title });
    if (await confirm(message)) {
      setDeleteError(null);
      archiveMutation.mutate(archived);
    }
  };

  // SOT-1411: 締切調査タスクの基準日(最終提出期限)を変更し、同じ締切調査グループの付随タスクを
  // 保存済みオフセットでまとめてずらす。
  const rescheduleMutation = useMutation({
    mutationFn: (baseDate: string) => rescheduleDeadline(id, baseDate),
    onSuccess: (res) => {
      setRescheduleError(null);
      setRescheduleMessage(t('records.rescheduleDone', { count: String(res.updated) }));
      setBaseDateInput(null);
      queryClient.invalidateQueries({ queryKey: ['info-detail', id] });
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
    },
    onError: () => {
      setRescheduleMessage(null);
      setRescheduleError(t('records.rescheduleError'));
    },
  });

  const handleReschedule = (baseDate: string) => {
    if (!baseDate || rescheduleMutation.isPending) return;
    setRescheduleMessage(null);
    setRescheduleError(null);
    rescheduleMutation.mutate(baseDate);
  };

  // SOT-1468: 写真の登録月(created_at)を変更する。既存の更新API (PUT /info/{id}) を再利用し、
  // 成功後に一覧(['info'])を無効化して月グループへ即時反映する。
  const monthMutation = useMutation({
    mutationFn: (createdAt: string) => updateInfo(id, { created_at: createdAt }),
    onSuccess: () => {
      setMonthError(null);
      setMonthMessage(t('records.registeredMonthSaved'));
      setMonthInput(null);
      queryClient.invalidateQueries({ queryKey: ['info-detail', id] });
      queryClient.invalidateQueries({ queryKey: ['info'] });
    },
    onError: () => {
      setMonthMessage(null);
      setMonthError(t('records.saveError'));
    },
  });

  const handleSaveMonth = () => {
    if (!item || monthMutation.isPending) return;
    const ym = monthInput ?? toMonthInput(item.created_at);
    const nextCreatedAt = applyMonthToCreatedAt(item.created_at, ym);
    if (!nextCreatedAt) return;
    setMonthMessage(null);
    setMonthError(null);
    monthMutation.mutate(nextCreatedAt);
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
            {/* SOT-1415: 編集モードではタイトルを入力欄にする。 */}
            {!hasPhoto && !isEditing && (
              <h1 className="flex-1 min-w-0 text-2xl font-bold text-foreground break-words">{item.title}</h1>
            )}
            {!hasPhoto && isEditing && (
              <input
                type="text"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                disabled={editMutation.isPending}
                aria-label={t('tasks.fieldTitle')}
                className="flex-1 text-lg font-bold text-foreground border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand p-2 disabled:opacity-60"
              />
            )}
            {/* SOT-1418: 編集ボタンを削除ボタンの下に配置するため縦並び（column）にする。 */}
            <div className="flex flex-col items-end gap-2 flex-shrink-0">
              {/* SOT-1419: 編集画面（編集モード）では削除ボタンを表示しない。
                  写真ありレコードは編集モードに入らないため、削除ボタンは従来どおり表示される。 */}
              {!isEditing && (
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteMutation.isPending}
                  className="text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1 rounded-md disabled:text-muted-foreground disabled:hover:bg-transparent transition-colors"
                >
                  {deleteMutation.isPending ? t('records.deleting') : t('records.delete')}
                </button>
              )}
              {/* SOT-1415: 詳細画面の「編集」ボタン。非写真タスクレコードのみ表示する。
                  SOT-1418: 削除ボタンの下に表示する。 */}
              {!hasPhoto && !isEditing && (
                <button
                  type="button"
                  onClick={handleStartEdit}
                  className="text-sm font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50 px-3 py-1 rounded-md transition-colors"
                >
                  {t('records.edit')}
                </button>
              )}
            </div>
          </div>

          {deleteError && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
              {deleteError}
            </div>
          )}

          {/* SOT-1468: 写真ありレコードでは登録月(created_at)を変更できる。
              写真一覧はこの登録月でグルーピングされるため、ここでの変更が一覧の月グループに反映される。
              SOT-1563(再オープン#2): 年月表示を、やることリストの年月日チップ
              (DatedInfoList の日付チップ = text-xs px-2 py-1 rounded-full + 緑 getStatusDateChipClass)と
              同じ大きさ・緑色・長丸(pill)枠に揃える。前回のオレンジ(brand-accent)基調を緑基調へ戻す。
              機能は変更しない。 */}
          {hasPhoto && (
            <div className="mb-4">
              <div className="flex flex-wrap items-center gap-2">
                <label htmlFor="registered-month" className="inline-flex items-center gap-1 text-sm font-medium text-green-800">
                  📅 {t('records.registeredMonth')}
                </label>
                <input
                  id="registered-month"
                  type="month"
                  value={monthInput ?? toMonthInput(item.created_at)}
                  onChange={(e) => {
                    setMonthInput(e.target.value);
                    setMonthMessage(null);
                  }}
                  disabled={monthMutation.isPending}
                  className="border border-green-200 bg-green-100 text-green-800 rounded-full shadow-sm focus:ring-green-500 focus:border-green-500 text-xs px-2 py-1 disabled:opacity-60"
                />
                <button
                  type="button"
                  onClick={handleSaveMonth}
                  disabled={monthMutation.isPending || !(monthInput ?? toMonthInput(item.created_at))}
                  className="text-xs font-medium text-green-800 border border-green-200 bg-green-100 hover:bg-green-200 px-3 py-1 rounded-full disabled:opacity-60 transition-colors"
                >
                  {monthMutation.isPending ? t('records.rescheduling') : t('records.registeredMonthSave')}
                </button>
              </div>
              {monthMessage && (
                <div className="mt-2 p-3 rounded-lg bg-green-100 border border-green-200 text-green-800 text-sm">
                  {monthMessage}
                </div>
              )}
              {monthError && (
                <div className="mt-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
                  {monthError}
                </div>
              )}
            </div>
          )}

          {/* SOT-1313: タスク等の詳細を確認できるよう、日付・ステータス・内容を値があるときのみ表示する。
              SOT-1331: 写真ありレコードはこれらを出さず、写真＋文字起こしのみにする。 */}
          {!hasPhoto && !isEditing && item.event_date && (
            <div className="mb-3">
              <span className="inline-flex items-center gap-1 text-sm font-medium bg-emerald-100 text-emerald-800 px-3 py-1 rounded-full">
                📅 {t('records.eventDate')}: {item.event_date}
              </span>
            </div>
          )}

          {/* SOT-1415: 編集モードでは日付(event_date)を変更できる（空にして日付なしにもできる）。
              SOT-1503: 表示画面の日付バッジ(bg-emerald-100 text-emerald-800)と同じ緑(emerald)基調の
              デザインに揃える（ラベルに📅アイコン＋emerald文字色、入力欄をemerald枠・薄緑背景・緑フォーカス）。
              SOT-1503(再オープン): 入力欄の「四角」の大きさをステータス変更欄(select, text-sm p-2)と揃えるため、
              フォント指定を sm:text-sm → text-sm に統一する（余白は両方 p-2 で同一）。 */}
          {!hasPhoto && isEditing && (
            <div className="mb-3">
              <div className="flex items-center gap-2">
                <label htmlFor="edit-event-date" className="inline-flex items-center gap-1 text-sm font-medium text-emerald-800">
                  📅 {t('records.eventDate')}
                </label>
                <input
                  id="edit-event-date"
                  type="date"
                  value={editDate}
                  onChange={(e) => setEditDate(e.target.value)}
                  disabled={editMutation.isPending}
                  className="border border-emerald-300 bg-emerald-50 text-emerald-900 rounded-md shadow-sm focus:ring-emerald-500 focus:border-emerald-500 text-sm p-2 disabled:opacity-60"
                />
              </div>
            </div>
          )}

          {/* SOT-1411: 締切調査由来タスクのうち、グループの基準（アンカー＝元タスク/親, offset 0）だけが
              締切の基準日(最終提出期限)を変更できる。基準日を変えると同じグループの子タスクが保存済み
              オフセットで一緒にずれる。子タスク(offset > 0)には基準日変更UIを出さない（再オープン対応）。
              基準日変更UIは編集画面(編集モード)のときだけ表示する（再オープン対応: isEditing ゲート）。 */}
          {!hasPhoto && isEditing && item.deadline_group_id && item.deadline_offset_days === 0 && (
            <div className="mb-4">
              <div className="flex flex-wrap items-center gap-2">
                <label htmlFor="reschedule-base-date" className="text-sm font-medium text-foreground">
                  {t('records.rescheduleBaseDate')}
                </label>
                <input
                  id="reschedule-base-date"
                  type="date"
                  value={baseDateInput ?? item.deadline_base_date ?? item.due_date ?? ''}
                  onChange={(e) => setBaseDateInput(e.target.value)}
                  disabled={rescheduleMutation.isPending}
                  className="border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2 disabled:opacity-60"
                />
                <button
                  type="button"
                  onClick={() =>
                    handleReschedule(baseDateInput ?? item.deadline_base_date ?? item.due_date ?? '')
                  }
                  disabled={rescheduleMutation.isPending}
                  className="text-sm font-medium text-brand-strong border border-accent-border bg-accent-bg hover:opacity-90 px-3 py-1.5 rounded-md disabled:opacity-60 transition-colors"
                >
                  {rescheduleMutation.isPending ? t('records.rescheduling') : t('records.rescheduleSave')}
                </button>
              </div>
              {rescheduleMessage && (
                <div className="mt-2 p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm">
                  {rescheduleMessage}
                </div>
              )}
              {rescheduleError && (
                <div className="mt-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
                  {rescheduleError}
                </div>
              )}
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
                  className="border-accent-border bg-accent-bg text-brand-strong rounded-md shadow-sm focus:ring-brand focus:border-brand text-sm p-2 border disabled:opacity-60"
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

          {!hasPhoto && !isEditing && item.content && (
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-muted-foreground mb-1">{t('records.content')}</h2>
              <LinkifiedText text={item.content} className="whitespace-pre-wrap break-words text-foreground" />
            </div>
          )}

          {/* SOT-1577: 「分割前のタスクに戻す」ボタン。本文と、写真リンク／アーカイブ行の間に配置する。
              仮登録画面(DraftsPage)と同じく、同一書類から2件以上に分割された本登録タスクの場合のみ表示し、
              押下でその分割グループを未分割の1タスクへまとめ直す。非写真タスク・編集モード以外で表示。 */}
          {!hasPhoto && !isEditing && isSplitGroup && (
            <div className="mt-4">
              <button
                type="button"
                onClick={handleRevertSplit}
                disabled={revertSplitMutation.isPending}
                className="px-4 py-2 text-sm font-medium text-brand-strong bg-surface border border-brand rounded-md hover:bg-accent-bg disabled:opacity-50"
              >
                {revertSplitMutation.isPending ? t('drafts.working') : t('drafts.revertSplit')}
              </button>
            </div>
          )}

          {/* SOT-1500: アーカイブ操作ボタン。再オープン対応で、内容の下・右下に配置し、
              日付バッジ(rounded-full ピル)と同じデザインで色を紫(purple)基調にする。
              アーカイブ済み(アーカイブ画面から開いた項目)は「アーカイブから戻す」に切り替える。
              非写真タスクレコードのみ・編集モード以外で表示する。 */}
          {!hasPhoto && !isEditing && (
            <div className="mt-4 flex items-center justify-between gap-2">
              {/* SOT-1562: このタスクの基になった元写真のタイトルをアーカイブの左に表示し、
                  クリックで元写真の詳細へ遷移する。参照が無い/元写真が取得できない場合は空要素で
                  レイアウトを保ち、アーカイブボタンを従来どおり右端に維持する。 */}
              {sourceInfoId && sourceInfo ? (
                <button
                  type="button"
                  onClick={() => navigate(`/data/${sourceInfoId}`)}
                  className="inline-flex min-w-0 items-center gap-1 text-sm font-medium text-brand hover:text-brand-strong hover:underline"
                >
                  <span aria-hidden="true">🖼️</span>
                  <span className="truncate">{sourceInfo.title}</span>
                </button>
              ) : (
                <span />
              )}
              <button
                type="button"
                onClick={handleArchive}
                disabled={archiveMutation.isPending}
                aria-label={item.is_archived ? t('records.unarchive') : t('records.archive')}
                className="inline-flex shrink-0 items-center gap-1 text-sm font-medium bg-purple-100 text-purple-800 px-3 py-1 rounded-full hover:bg-purple-200 disabled:opacity-60 transition-colors"
              >
                <span aria-hidden="true">{item.is_archived ? '♻️' : '🗄️'}</span>
                {archiveMutation.isPending
                  ? item.is_archived
                    ? t('records.unarchiving')
                    : t('records.archiving')
                  : item.is_archived
                    ? t('records.unarchive')
                    : t('records.archive')}
              </button>
            </div>
          )}

          {/* SOT-1415: 編集モードでは内容(content)をテキストエリアで変更できる。 */}
          {!hasPhoto && isEditing && (
            <div className="mb-4">
              <label htmlFor="edit-content" className="block text-sm font-semibold text-muted-foreground mb-1">
                {t('records.content')}
              </label>
              <textarea
                id="edit-content"
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                disabled={editMutation.isPending}
                rows={4}
                className="w-full rounded-md border border-border bg-surface px-3 py-2 text-foreground focus:ring-brand focus:border-brand disabled:opacity-60"
              />
            </div>
          )}

          {/* SOT-1415: 編集モードの保存／キャンセル。 */}
          {!hasPhoto && isEditing && (
            <div className="mb-4">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSaveEdit}
                  disabled={editMutation.isPending}
                  className="text-sm font-medium text-brand-strong border border-accent-border bg-accent-bg hover:opacity-90 px-4 py-1.5 rounded-md disabled:opacity-60 transition-colors"
                >
                  {t('records.save')}
                </button>
                <button
                  type="button"
                  onClick={handleCancelEdit}
                  disabled={editMutation.isPending}
                  className="text-sm font-medium text-muted-foreground hover:bg-surface-muted px-4 py-1.5 rounded-md disabled:opacity-60 transition-colors"
                >
                  {t('records.cancel')}
                </button>
              </div>
              {editError && (
                <div className="mt-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
                  {editError}
                </div>
              )}
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
