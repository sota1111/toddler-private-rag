import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { getInfoById, deleteInfo, getAttachmentFileUrl } from '../api';
import { useI18n } from '../i18n/useI18n';

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
      navigate('/data');
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
    <Link to="/data" className="inline-flex items-center text-sm font-medium text-brand hover:text-brand-strong mb-4">
      ‹ {t('records.back')}
    </Link>
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

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      {backLink}

      <div className="bg-surface rounded-lg shadow-sm border border-border overflow-hidden">
        <div className="p-4 sm:p-6">
          <div className="flex items-start justify-between gap-3 mb-4">
            <h1 className="text-2xl font-bold text-foreground break-words">{item.title}</h1>
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

          {item.attachments && item.attachments.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
              {item.attachments.map((att) => (
                <div key={att.id} className="relative group">
                  {att.mime_type.startsWith('image/') ? (
                    <div className="aspect-square bg-border rounded-md overflow-hidden border border-border">
                      <img
                        src={getAttachmentFileUrl(att.id)}
                        alt={att.original_filename}
                        className="w-full h-full object-cover cursor-pointer hover:opacity-90 transition-opacity"
                        loading="lazy"
                        onClick={() => window.open(getAttachmentFileUrl(att.id), '_blank')}
                      />
                    </div>
                  ) : (
                    <a
                      href={getAttachmentFileUrl(att.id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="aspect-square flex flex-col items-center justify-center bg-surface rounded-md border border-border p-2 hover:bg-surface-muted transition-colors"
                    >
                      <svg className="w-8 h-8 text-muted-foreground mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                      </svg>
                      <span className="text-[10px] text-muted-foreground text-center line-clamp-2 break-all px-1">
                        {att.original_filename}
                      </span>
                    </a>
                  )}
                </div>
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
