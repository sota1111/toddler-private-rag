import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getDrafts, finalizeInfo, deleteInfo, getAttachmentFileUrl } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';

// 登録ページ (SOT-1113): 自動登録した写真の仮登録(draft)一覧。
// 内容を確認のうえ本登録(finalize)、または破棄(delete)できる。
const DraftsPage: React.FC = () => {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { data: drafts, isLoading, isError } = useQuery({
    queryKey: ['drafts'],
    queryFn: getDrafts,
  });
  const [busyId, setBusyId] = useState<number | null>(null);

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

  const handleFinalize = async (id: number) => {
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

  const handleDiscard = async (id: number) => {
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

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-2 text-foreground">{t('drafts.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('drafts.desc')}</p>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {isError && <p className="text-sm text-red-600">{t('drafts.loadError')}</p>}

      {!isLoading && !isError && (!drafts || drafts.length === 0) && (
        <div className="bg-surface border border-border rounded-lg p-8 text-center text-muted-foreground">
          {t('drafts.empty')}
        </div>
      )}

      <div className="space-y-4">
        {drafts?.map((d: NurseryInfo) => {
          const imageAtt = d.attachments?.find((a) => a.mime_type?.startsWith('image/'));
          const busy = busyId === d.id;
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
                <div className="min-w-0 flex-1 space-y-1.5">
                  <h2 className="text-lg font-semibold text-foreground break-words">
                    {d.title || t('drafts.untitled')}
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    {t('drafts.type')}: {d.info_type}
                    {d.date ? ` ・ ${t('drafts.date')}: ${d.date}` : ''}
                  </p>
                  {d.content && (
                    <p className="text-sm text-foreground whitespace-pre-wrap line-clamp-4">{d.content}</p>
                  )}
                  {d.items && (
                    <p className="text-sm text-muted-foreground">
                      {t('drafts.items')}: {d.items}
                    </p>
                  )}
                  {d.memo && (
                    <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                      {t('drafts.memo')}: {d.memo}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-3 justify-end mt-4 pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => handleDiscard(d.id)}
                  disabled={busy}
                  className="px-4 py-2 text-sm font-medium text-red-600 bg-surface border border-red-200 rounded-md hover:bg-red-50 disabled:opacity-50"
                >
                  {busy ? t('drafts.working') : t('drafts.discard')}
                </button>
                <button
                  type="button"
                  onClick={() => handleFinalize(d.id)}
                  disabled={busy}
                  className="px-5 py-2 text-sm font-medium text-white bg-brand rounded-md shadow-sm hover:bg-brand-strong disabled:opacity-50"
                >
                  {busy ? t('drafts.working') : t('drafts.finalize')}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DraftsPage;
