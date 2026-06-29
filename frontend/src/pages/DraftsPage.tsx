import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getDrafts, finalizeInfo, deleteInfo, updateInfo, getAttachmentFileUrl, getProcessingCount } from '../api';
import type { NurseryInfo, NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import RegisterMenu from '../components/RegisterMenu';
import ScrollableDatePicker from '../components/ScrollableDatePicker';
import { INFO_TYPES, STATUS_TYPES, PRIORITY_TYPES } from './infoFormOptions';

// 登録ページ (SOT-1113): 自動登録した写真の仮登録(draft)一覧。
// 内容を確認のうえ本登録(finalize)、または破棄(delete)できる。
// SOT-1216: 各登録項目を表示したうえで、カードごとにインライン編集・保存できる。
const DraftsPage: React.FC = () => {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { data: drafts, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['drafts'],
    queryFn: getDrafts,
  });
  // SOT-1380: 写真アップ後、OCR(文字起こし)中のレコード(processing)は仮登録一覧にまだ出ない。
  // その件数を取得し、「文字起こし中」インジケータを表示する。完了すると 0 になり自動的に消える。
  const { data: processingCount = 0 } = useQuery({
    queryKey: ['drafts', 'processing-count'],
    queryFn: getProcessingCount,
    refetchInterval: 5000,
  });
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
    if (!window.confirm(t('drafts.confirmFinalizeAll'))) return;
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
    if (!window.confirm(t('drafts.confirmDiscard'))) return;
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
          className="flex-shrink-0 p-2 text-foreground bg-surface border border-brand rounded-md hover:bg-surface-muted disabled:opacity-50"
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

      {!isLoading && !isError && (!drafts || drafts.length === 0) && (
        <div className="bg-surface border border-border rounded-lg p-8 text-center text-muted-foreground">
          {t('drafts.empty')}
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
        {drafts?.map((d: NurseryInfo) => {
          const imageAtt = d.attachments?.find((a) => a.mime_type?.startsWith('image/'));
          const busy = busyId === d.id;
          // SOT-1323: いずれかの項目を処理中の間は、全カードのボタンを無効化して
          // 多重リクエスト/状態競合を防ぐ（処理中の項目だけ「処理中…」表示を維持）。
          const anyBusy = busyId !== null || bulkBusy;
          const isEditing = editingId === d.id && editForm !== null;
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
