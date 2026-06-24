import React, { useEffect, useState } from 'react';
import { useI18n } from '../i18n/useI18n';

// メモページ (SOT-1203): 自由にメモを記入し「登録」ボタンで保存できる。
// 永続化はブラウザ内 localStorage で完結させ、バックエンド改修なしで動作する。
type Memo = {
  id: number;
  text: string;
  createdAt: string;
};

const STORAGE_KEY = 'toddler-memos';

const loadMemos = (): Memo[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (m): m is Memo =>
        m && typeof m.id === 'number' && typeof m.text === 'string' && typeof m.createdAt === 'string',
    );
  } catch (e) {
    console.error('Failed to load memos', e);
    return [];
  }
};

const MemoPage: React.FC = () => {
  const { t } = useI18n();
  const [memos, setMemos] = useState<Memo[]>(() => loadMemos());
  const [text, setText] = useState('');

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(memos));
    } catch (e) {
      console.error('Failed to save memos', e);
    }
  }, [memos]);

  const handleRegister = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const memo: Memo = { id: Date.now(), text: trimmed, createdAt: new Date().toISOString() };
    setMemos((prev) => [memo, ...prev]);
    setText('');
  };

  const handleDelete = (id: number) => {
    setMemos((prev) => prev.filter((m) => m.id !== id));
  };

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-2 text-foreground">{t('memo.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('memo.desc')}</p>

      <div className="bg-surface shadow-sm border border-border rounded-lg p-5 mb-6">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('memo.placeholder')}
          rows={5}
          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40 resize-y"
        />
        <div className="flex justify-end mt-3">
          <button
            type="button"
            onClick={handleRegister}
            disabled={!text.trim()}
            className="px-5 py-2 text-sm font-medium text-white bg-brand rounded-md shadow-sm hover:bg-brand-strong disabled:opacity-50"
          >
            {t('memo.register')}
          </button>
        </div>
      </div>

      {memos.length === 0 ? (
        <div className="bg-surface border border-border rounded-lg p-8 text-center text-muted-foreground">
          {t('memo.empty')}
        </div>
      ) : (
        <div className="space-y-4">
          {memos.map((m) => (
            <div key={m.id} className="bg-surface shadow-sm border border-border rounded-lg p-5">
              <p className="text-sm text-foreground whitespace-pre-wrap break-words">{m.text}</p>
              <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
                <span className="text-xs text-muted-foreground">
                  {new Date(m.createdAt).toLocaleString()}
                </span>
                <button
                  type="button"
                  onClick={() => handleDelete(m.id)}
                  className="px-3 py-1.5 text-sm font-medium text-red-600 bg-surface border border-red-200 rounded-md hover:bg-red-50"
                >
                  {t('memo.delete')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MemoPage;
