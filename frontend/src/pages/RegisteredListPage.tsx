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
// SOT-1468: 写真データを登録月(created_at)ごとにグルーピングして表示する。
//   月見出し（例: 2026年7月 / July 2026）を付け、新しい月から順（降順）に並べ、
//   各グループ内も新しい順（降順）に並べる。

// created_at から年月キー(YYYY-MM)を取り出す。値が不正なら空文字（末尾グループに集約）。
const monthKey = (item: NurseryInfo): string => {
  const d = new Date(item.created_at);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

const RegisteredListPage: React.FC = () => {
  const { t, lang } = useI18n();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['info', 'registered'],
    queryFn: () => getInfoList(),
  });

  // 写真(添付)を持つレコードのみを登録一覧に表示する。
  const items = (data ?? []).filter((it) => (it.attachments?.length ?? 0) > 0);

  // 登録月ごとにグルーピングし、新しい月順・グループ内も新しい順（created_at 降順）に並べる。
  // 月見出しは SchedulePage と同じ Intl パターン（ja: 2026年7月 / en: July 2026）。
  const groups = React.useMemo(() => {
    const monthFormatter = new Intl.DateTimeFormat(lang === 'ja' ? 'ja-JP' : 'en-US', {
      year: 'numeric',
      month: 'long',
    });
    const byMonth = new Map<string, NurseryInfo[]>();
    for (const item of items) {
      const key = monthKey(item);
      const bucket = byMonth.get(key);
      if (bucket) bucket.push(item);
      else byMonth.set(key, [item]);
    }
    return Array.from(byMonth.entries())
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([key, groupItems]) => {
        let label = '';
        if (key) {
          const [y, m] = key.split('-').map(Number);
          label = monthFormatter.format(new Date(y, m - 1, 1));
        }
        return {
          key,
          label,
          items: [...groupItems].sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
          ),
        };
      });
  }, [items, lang]);

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

      <div className="space-y-6">
        {groups.map((group) => (
          <section key={group.key || 'unknown'}>
            {group.label && (
              <h2 className="mb-2 text-sm font-semibold text-muted-foreground">{group.label}</h2>
            )}
            <ul className="space-y-2">
              {group.items.map((item: NurseryInfo) => (
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
          </section>
        ))}
      </div>
    </div>
  );
};

export default RegisteredListPage;
