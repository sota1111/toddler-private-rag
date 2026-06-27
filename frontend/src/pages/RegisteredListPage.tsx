import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getInfoList } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import RegisterMenu from '../components/RegisterMenu';

// 登録一覧 (SOT-1311): 本登録(registered)データのタイトル一覧。
// タイトルをクリックすると詳細画面 /data/:id（タイトル+写真+削除）へ遷移する。
// データ取得は getInfoList(GET /info/)=本登録のみ（draft は除外）。
// SOT-1318: タスクと写真を別扱いにする。登録一覧は「写真(添付)を持つレコード」のみ表示し、
// タスク(予定日つき・写真なし)は出さない（タスクは TasksPage /tasks に表示される）。
const RegisteredListPage: React.FC = () => {
  const { t } = useI18n();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['info', 'registered'],
    queryFn: () => getInfoList(),
  });

  // 写真(添付)を持つレコードのみを登録一覧に表示する。
  const items = (data ?? []).filter((it) => (it.attachments?.length ?? 0) > 0);

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto pb-12">
      <RegisterMenu />
      <h1 className="text-2xl font-bold mb-2 text-foreground">{t('registered.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('registered.desc')}</p>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {isError && <p className="text-sm text-red-600">{t('registered.loadError')}</p>}

      {!isLoading && !isError && (!items || items.length === 0) && (
        <div className="bg-surface border border-border rounded-lg p-8 text-center text-muted-foreground">
          {t('registered.empty')}
        </div>
      )}

      <ul className="space-y-2">
        {items?.map((item: NurseryInfo) => (
          <li key={item.id}>
            <Link
              to={`/data/${item.id}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-foreground shadow-sm transition-colors hover:border-brand/40 hover:bg-brand/10 focus:outline-none focus:ring-2 focus:ring-brand/40"
            >
              <span className="min-w-0 break-words font-medium">
                {item.title || t('registered.untitled')}
              </span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-5 w-5 flex-shrink-0 text-muted-foreground"
                aria-hidden
              >
                <path d="M9 18l6-6-6-6" />
              </svg>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default RegisteredListPage;
