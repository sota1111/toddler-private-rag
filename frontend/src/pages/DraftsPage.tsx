import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getDrafts, finalizeInfo, deleteInfo, updateInfo, getAttachmentFileUrl, getProcessingDrafts, revertSplitDrafts } from '../api';
import type { NurseryInfo, NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { useConfirm } from '../components/confirmDialogContext';
import RegisterMenu from '../components/RegisterMenu';
import ScrollableDatePicker from '../components/ScrollableDatePicker';
import { INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES } from './infoFormOptions';
import { isAgentSplitTask, shouldShowRevertSplit } from '../utils/splitTasks';

// 登録ページ (SOT-1113): 自動登録した写真の仮登録(draft)一覧。
// 内容を確認のうえ本登録(finalize)、または破棄(delete)できる。
// SOT-1216: 各登録項目を表示したうえで、カードごとにインライン編集・保存できる。
const DraftsPage: React.FC = () => {
  const { t } = useI18n();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: drafts, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['drafts'],
    queryFn: getDrafts,
  });
  // SOT-1380 / SOT-1499: 写真アップ後、OCR(文字起こし=読み取り)中のレコード(processing)は
  // enrich が終わるまで仮登録(draft)一覧には出ない。追加で自動登録した写真を完了前でも確認できる
  // よう、読み取り中の項目を取得して「読み取り中」カードとして表示する。完了すると draft に昇格し
  // 通常の仮登録カードへ置き換わる。5秒ごとにポーリングし自動更新する。
  const { data: processingDrafts } = useQuery({
    queryKey: ['drafts', 'processing'],
    queryFn: getProcessingDrafts,
    refetchInterval: 5000,
  });
  const processingItems = processingDrafts ?? [];
  const processingCount = processingItems.length;
  // SOT-1380 follow-up: processingCount(=サーバ側OCR処理中件数)だけだと、
  // 写真アップ完了画面→仮登録画面へ移動した時点では OCR が既に終わっている／5秒ポーリングの
  // 谷間で 0 になりやすく、「写真アップ直後」に文字起こし中メッセージが出ないことがあった。
  // AutoRegisterPage がアップ成功時に保存する直近アップロード時刻を読み、一定時間内(=写真アップ
  // 直後)であれば processingCount に依らず文字起こし中とみなす。仮登録が表示されるか、ウィンドウ
  // (90秒)を過ぎれば自動的に通常表示へ戻る。時刻参照は副作用(useEffect)で行い、レンダーを純粋に保つ。
  const readRecentRemainingMs = () => {
    let ts: number;
    try {
      ts = Number(sessionStorage.getItem('tpr.lastPhotoUploadAt') || 0);
    } catch {
      ts = 0;
    }
    return ts > 0 ? 90_000 - (Date.now() - ts) : 0;
  };
  // マウント時点(=仮登録画面に来た瞬間)の判定を lazy initializer で一度だけ確定し、
  // 残り時間が尽きたら setTimeout(非同期)で解除する。レンダー中に時刻参照しないため純粋。
  const [recentUpload, setRecentUpload] = useState(() => readRecentRemainingMs() > 0);
  useEffect(() => {
    const remaining = readRecentRemainingMs();
    if (remaining <= 0) return;
    const timer = setTimeout(() => setRecentUpload(false), remaining);
    return () => clearTimeout(timer);
  }, []);
  // 一覧が空のときに「文字起こし中」表示を出すかどうか。
  const showProcessing = processingCount > 0 || recentUpload;
  const [busyId, setBusyId] = useState<number | string | null>(null);
  // SOT-1341: 「全て本登録する」処理中フラグ（個別 busyId とは別に管理）
  const [bulkBusy, setBulkBusy] = useState(false);
  const [editingId, setEditingId] = useState<number | string | null>(null);
  const [editForm, setEditForm] = useState<NurseryInfoCreate | null>(null);

  // 種別/ステータス/優先度などの選択肢ラベル（保存値は日本語のまま）
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const refreshAll = async () => {
    // SOT-1409: refreshAll は本登録(finalize)/破棄(discard)/編集保存など、既に表示済みの
    // 仮登録を操作したときだけ呼ばれる。これらの時点で文字起こし(OCR)は完了しているため、
    // 写真アップ直後の90秒ウィンドウ(recentUpload)を解除し、保存済みのアップロード時刻も消す。
    // これをしないと本登録で一覧が空に戻った後も空表示に「写真を文字起こし中です…」が残る。
    setRecentUpload(false);
    try {
      sessionStorage.removeItem('tpr.lastPhotoUploadAt');
    } catch {
      /* ignore */
    }
    // 仮登録の変化は通常の一覧/ダッシュボードにも影響するため広く無効化する
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['drafts'] }),
      queryClient.invalidateQueries({ queryKey: ['info'] }),
      queryClient.invalidateQueries({ queryKey: ['today'] }),
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] }),
      queryClient.invalidateQueries({ queryKey: ['weekly'] }),
      queryClient.invalidateQueries({ queryKey: ['pending'] }),
    ]);
  };

  const startEdit = (d: NurseryInfo) => {
    setEditingId(d.id);
    setEditForm({
      title: d.title ?? '',
      info_type: d.info_type ?? '資料',
      content: d.content ?? '',
      date: d.date ?? '',
      event_date: d.event_date ?? '',
      due_date: d.due_date ?? '',
      items: d.items ?? '',
      status: d.status ?? '未確認',
      priority: d.priority ?? '普通',
      tags: d.tags ?? '',
      memo: d.memo ?? '',
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm(null);
  };

  const handleEditChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => {
    const { name, value } = e.target;
    setEditForm(prev => (prev ? { ...prev, [name]: value } : prev));
  };

  const handleSaveEdit = async (id: number | string) => {
    if (!editForm) return;
    setBusyId(id);
    try {
      await updateInfo(id, editForm);
      await refreshAll();
      cancelEdit();
    } catch (e) {
      console.error('Failed to update draft', e);
      window.alert(t('drafts.actionFail'));
    } finally {
      setBusyId(null);
    }
  };

  const handleFinalize = async (id: number | string) => {
    setBusyId(id);
    try {
      await finalizeInfo(id);
      await refreshAll();
    } catch (e) {
      console.error('Failed to finalize draft', e);
      window.alert(t('drafts.actionFail'));
    } finally {
      setBusyId(null);
    }
  };

  // SOT-1341: 取得済みの全 draft を順番に本登録する。部分失敗の扱いを明確にするため逐次実行。
  const handleFinalizeAll = async () => {
    if (!drafts || drafts.length === 0) return;
    if (!(await confirm(t('drafts.confirmFinalizeAll')))) return;
    setBulkBusy(true);
    try {
      for (const d of drafts) {
        await finalizeInfo(d.id);
      }
    } catch (e) {
      console.error('Failed to finalize all drafts', e);
      window.alert(t('drafts.actionFail'));
    } finally {
      await refreshAll();
      setBulkBusy(false);
    }
  };

  const handleDiscard = async (id: number | string) => {
    if (!(await confirm(t('drafts.confirmDiscard')))) return;
    setBusyId(id);
    try {
      await deleteInfo(id);
      await refreshAll();
    } catch (e) {
      console.error('Failed to discard draft', e);
      window.alert(t('drafts.actionFail'));
    } finally {
      setBusyId(null);
    }
  };

  // SOT-1577 / SOT-1594: 「分割前のタスクに戻す」。押下した (n/N) 分割タスク自身の id を渡し、その
  // タスクが属する締切グループだけを未分割の1 draft へまとめ直す（同じ写真由来でも別書類・別グループの
  // draft は残す）。旧実装は source_info_id を渡し書類全タスクを1つに潰していた。
  const handleRevertSplit = async (id: number | string) => {
    if (!(await confirm(t('drafts.confirmRevertSplit')))) return;
    setBusyId(id);
    try {
      await revertSplitDrafts(id);
      await refreshAll();
      // SOT-1596: 分割を戻したあとはやることリスト一覧ページへ遷移する。
      navigate('/tasks');
    } catch (e) {
      console.error('Failed to revert split drafts', e);
      window.alert(t('drafts.actionFail'));
    } finally {
      setBusyId(null);
    }
  };

  // SOT-1584: 「分割前に戻す」は、エージェントが (1/4) のように分割したタスク群にのみ出す。
  // source_info_id ごとに「(n/N) 分割マーカーを持つ分割タスク」の件数を数える（手動 draft や、
  // 1枚から複数の独立タスクが出ただけのケースはマーカーが無いので対象外）。
  const splitGroupCounts = new Map<string, number>();
  for (const d of drafts ?? []) {
    const key = d.source_info_id != null ? String(d.source_info_id) : '';
    if (key && isAgentSplitTask(d)) {
      splitGroupCounts.set(key, (splitGroupCounts.get(key) ?? 0) + 1);
    }
  }

  const inputCls = 'mt-1 block w-full border border-border rounded-md shadow-sm p-2 text-sm';

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto pb-12">
      <RegisterMenu />
      {/* SOT-1379: 見出しの右側に「更新」ボタンを置き、写真アップ後に非同期で増える仮登録を手動で再取得できるようにする。 */}
      <div className="flex items-start justify-between gap-3 mb-6">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold mb-2 text-foreground">{t('drafts.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('drafts.desc')}</p>
        </div>
        <button
          type="button"
          onClick={() => { void refetch(); }}
          disabled={isFetching}
          aria-label={isFetching ? t('drafts.refreshing') : t('drafts.refresh')}
          title={isFetching ? t('drafts.refreshing') : t('drafts.refresh')}
          className="flex-shrink-0 p-2 text-white bg-brand border border-brand rounded-md hover:bg-brand-strong disabled:opacity-50"
        >
          {/* SOT-1379: 「更新」はテキストではなくアイコン（円形矢印）。取得中は回転。ラベルは aria-label/title が担う。 */}
          <svg
            className={`w-5 h-5${isFetching ? ' animate-spin' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      {/* SOT-1380: 写真の文字起こし中(processing)があることを伝えるインジケータ。完了で自動的に消える。 */}
      {processingCount > 0 && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-accent-border bg-accent-bg px-4 py-3 text-sm text-brand-strong">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-brand" aria-hidden="true" />
          {t('drafts.processing', { count: processingCount })}
        </div>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {isError && <p className="text-sm text-red-600">{t('drafts.loadError')}</p>}

      {/* SOT-1499: 読み取り中の項目はカードで下に表示する（processingCount > 0）。
          一覧も読み取り中も無い場合のみ空表示。写真アップ直後(recentUpload)でまだ processing が
          サーバに現れていない谷間だけ、従来の「文字起こし中」テキストで補う。 */}
      {!isLoading && !isError && (!drafts || drafts.length === 0) && processingCount === 0 && (
        <div className="bg-surface border border-border rounded-lg p-8 text-center text-muted-foreground">
          {showProcessing ? t('drafts.emptyProcessing') : t('drafts.empty')}
        </div>
      )}

      {!isLoading && !isError && drafts && drafts.length > 0 && (
        <div className="flex justify-end mb-4">
          <button
            type="button"
            onClick={handleFinalizeAll}
            disabled={busyId !== null || bulkBusy}
            className="px-5 py-2 text-sm font-medium text-white bg-brand rounded-md shadow-sm hover:bg-brand-strong disabled:opacity-50"
          >
            {bulkBusy ? t('drafts.working') : t('drafts.finalizeAll')}
          </button>
        </div>
      )}

      <div className="space-y-4">
        {/* SOT-1499: 追加で自動登録した写真のうち、まだ文字起こし(読み取り)中の項目を
            「読み取り中」カードとして表示する。内容確認・本登録は昇格後の仮登録カードで行うため、
            ここでは写真と読み取り中バッジのみの読み取り専用カードにする。 */}
        {processingItems.map((p: NurseryInfo) => {
          const imageAtt = p.attachments?.find((a) => a.mime_type?.startsWith('image/'));
          return (
            <div
              key={`processing-${p.id}`}
              className="bg-surface shadow-sm border border-dashed border-brand rounded-lg p-5"
              aria-busy="true"
            >
              <div className="flex flex-col sm:flex-row items-center gap-4">
                {imageAtt && (
                  <img
                    src={getAttachmentFileUrl(imageAtt.id)}
                    alt={p.title || t('drafts.processingCardTitle')}
                    className="w-full sm:w-40 h-40 object-cover rounded-md border border-border flex-shrink-0 opacity-70"
                  />
                )}
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="inline-flex items-center gap-2 rounded-full bg-accent-bg px-3 py-1 text-xs font-medium text-brand-strong">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-brand" aria-hidden="true" />
                    {t('drafts.processingBadge')}
                  </div>
                  <h2 className="text-lg font-semibold text-foreground break-words">
                    {p.title || t('drafts.processingCardTitle')}
                  </h2>
                  <p className="text-sm text-muted-foreground">{t('drafts.processingCardHint')}</p>
                </div>
              </div>
            </div>
          );
        })}
        {drafts?.map((d: NurseryInfo) => {
          const imageAtt = d.attachments?.find((a) => a.mime_type?.startsWith('image/'));
          const busy = busyId === d.id;
          // SOT-1323: いずれかの項目を処理中の間は、全カードのボタンを無効化して
          // 多重リクエスト/状態競合を防ぐ（処理中の項目だけ「処理中…」表示を維持）。
          const anyBusy = busyId !== null || bulkBusy;
          const isEditing = editingId === d.id && editForm !== null;
          // SOT-1584 / SOT-1588: 「分割前に戻す」は、同一書類から (1/4) のように2件以上へ分割された
          // グループの、かつ **このカード自身が (n/N) 分割タスク** の場合にのみ表示する。グループ件数だけを
          // 見ていた旧判定は、同じ写真から登録された非分割の他タスクにもボタンを出してしまっていた。
          const sourceInfoId = d.source_info_id != null ? String(d.source_info_id) : '';
          const isSplitGroup = shouldShowRevertSplit(d, splitGroupCounts.get(sourceInfoId) ?? 0);
          return (
            <div key={d.id} className="bg-surface shadow-sm border border-border rounded-lg p-5">
              <div className="flex flex-col sm:flex-row gap-4">
                {imageAtt && (
                  <img
                    src={getAttachmentFileUrl(imageAtt.id)}
                    alt={imageAtt.original_filename}
                    className="w-full sm:w-40 h-40 object-cover rounded-md border border-border flex-shrink-0"
                  />
                )}

                {isEditing && editForm ? (
                  <div className="min-w-0 flex-1 space-y-3">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="md:col-span-2">
                        <label className="block text-sm font-medium text-foreground">{t('create.fieldTitle')}</label>
                        <input type="text" name="title" className={inputCls} value={editForm.title} onChange={handleEditChange} />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground">{t('create.fieldType')}</label>
                        <select name="info_type" className={inputCls} value={editForm.info_type} onChange={handleEditChange}>
                          {INFO_TYPES.map(v => <option key={v} value={v}>{optLabel('infoType', v)}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground">{t('create.fieldStatus')}</label>
                        <select name="status" className={inputCls} value={editForm.status} onChange={handleEditChange}>
                          {STATUS_TYPES.map(s => <option key={s} value={s}>{optLabel('status', s)}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground">{t('create.fieldPriority')}</label>
                        <select name="priority" className={inputCls} value={editForm.priority} onChange={handleEditChange}>
                          {PRIORITY_TYPES.map(p => <option key={p} value={p}>{optLabel('priority', p)}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground">{t('create.fieldDate')}</label>
                        <input type="date" name="date" className={inputCls} value={editForm.date} onChange={handleEditChange} />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground">{t('create.fieldEventDate')}</label>
                        {/* SOT-1307: 予定日はスクロールで選択する */}
                        <ScrollableDatePicker
                          value={editForm.event_date ?? ''}
                          onChange={(iso) => setEditForm(prev => (prev ? { ...prev, event_date: iso } : prev))}
                          ariaLabel={t('create.fieldEventDate')}
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground">{t('create.fieldDueDate')}</label>
                        <input type="date" name="due_date" className={inputCls} value={editForm.due_date} onChange={handleEditChange} />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-foreground">{t('create.fieldContent')}</label>
                      <textarea name="content" rows={8} className={inputCls} value={editForm.content} onChange={handleEditChange} />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-foreground">{t('create.fieldItems')}</label>
                      <textarea name="items" rows={3} className={inputCls} placeholder={t('create.itemsPlaceholder')} value={editForm.items} onChange={handleEditChange} />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-foreground">{t('create.fieldTags')}</label>
                      <input type="text" name="tags" className={inputCls} placeholder={t('create.tagsPlaceholder')} value={editForm.tags} onChange={handleEditChange} />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-foreground">{t('create.fieldMemo')}</label>
                      <textarea name="memo" rows={5} className={inputCls} value={editForm.memo} onChange={handleEditChange} />
                    </div>
                  </div>
                ) : (
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <h2 className="text-lg font-semibold text-foreground break-words">
                      {d.title || t('drafts.untitled')}
                    </h2>
                    <p className="text-xs text-muted-foreground">
                      <span className="font-semibold text-foreground">{t('drafts.type')}:</span> {optLabel('infoType', d.info_type)}
                      {d.date ? (
                        <>
                          {' ・ '}
                          <span className="font-semibold text-foreground">{t('drafts.date')}:</span> {d.date}
                        </>
                      ) : ''}
                      {d.event_date ? (
                        <>
                          {' ・ '}
                          <span className="font-semibold text-foreground">{t('drafts.eventDate')}:</span> {d.event_date}
                        </>
                      ) : ''}
                    </p>
                    {d.content && (
                      <p className="text-sm text-foreground whitespace-pre-wrap line-clamp-4">{d.content}</p>
                    )}
                    {d.items && (
                      <p className="text-sm text-muted-foreground">
                        <span className="font-semibold text-foreground">{t('drafts.items')}:</span> {d.items}
                      </p>
                    )}
                    {d.memo && (
                      <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                        <span className="font-semibold text-foreground">{t('drafts.memo')}:</span> {d.memo}
                      </p>
                    )}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-3 justify-end mt-4 pt-4 border-t border-border">
                {isEditing ? (
                  <>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      disabled={anyBusy}
                      className="px-4 py-2 text-sm font-medium text-foreground bg-surface border border-border rounded-md hover:bg-surface-muted disabled:opacity-50"
                    >
                      {t('drafts.cancel')}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSaveEdit(d.id)}
                      disabled={anyBusy}
                      className="px-5 py-2 text-sm font-medium text-white bg-brand rounded-md shadow-sm hover:bg-brand-strong disabled:opacity-50"
                    >
                      {busy ? t('drafts.working') : t('drafts.save')}
                    </button>
                  </>
                ) : (
                  <>
                    {isSplitGroup && (
                      <button
                        type="button"
                        onClick={() => handleRevertSplit(d.id)}
                        disabled={anyBusy}
                        className="px-4 py-2 text-sm font-medium text-brand-strong bg-surface border border-brand rounded-md hover:bg-accent-bg disabled:opacity-50"
                      >
                        {busy ? t('drafts.working') : t('drafts.revertSplit')}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDiscard(d.id)}
                      disabled={anyBusy}
                      className="px-4 py-2 text-sm font-medium text-red-600 bg-surface border border-red-200 rounded-md hover:bg-red-50 disabled:opacity-50"
                    >
                      {busy ? t('drafts.working') : t('drafts.discard')}
                    </button>
                    <button
                      type="button"
                      onClick={() => startEdit(d)}
                      disabled={anyBusy}
                      className="px-4 py-2 text-sm font-medium text-foreground bg-surface border border-border rounded-md hover:bg-surface-muted disabled:opacity-50"
                    >
                      {t('drafts.edit')}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleFinalize(d.id)}
                      disabled={anyBusy}
                      className="px-5 py-2 text-sm font-medium text-white bg-brand rounded-md shadow-sm hover:bg-brand-strong disabled:opacity-50"
                    >
                      {busy ? t('drafts.working') : t('drafts.finalize')}
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DraftsPage;
