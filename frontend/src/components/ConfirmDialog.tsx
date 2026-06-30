import { useCallback, useState, type ReactNode } from 'react';
import { useI18n } from '../i18n/useI18n';
import { ConfirmContext, type ConfirmFn } from './confirmDialogContext';

// SOT-1401: アプリ内のOK/キャンセルのみの確認モーダル。
// ブラウザ標準の window.confirm() は連続表示時に「このページでこれ以上ダイアログを生成しない」
// というチェックを自動で差し込む。それを排除し、選択肢を OK / キャンセルのみにするための代替。
interface DialogState {
  message: string;
  resolve: (value: boolean) => void;
}

export function ConfirmDialogProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [state, setState] = useState<DialogState | null>(null);

  const confirm = useCallback<ConfirmFn>((message) => {
    return new Promise<boolean>((resolve) => {
      // 既に表示中のものがあれば false で畳んでから新しいものを出す。
      setState((prev) => {
        if (prev) prev.resolve(false);
        return { message, resolve };
      });
    });
  }, []);

  const close = useCallback((value: boolean) => {
    setState((prev) => {
      if (prev) prev.resolve(value);
      return null;
    });
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => close(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-sm rounded-lg bg-surface p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-sm text-foreground whitespace-pre-line">{state.message}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => close(false)}
                className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface-muted"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                autoFocus
                onClick={() => close(true)}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-strong"
              >
                {t('common.ok')}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
