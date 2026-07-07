import { useCallback, useState, type ReactNode } from 'react';
import { useI18n } from '../i18n/useI18n';
import {
  ConfirmContext,
  type ConfirmFn,
  type ConfirmCheckboxOptions,
  type ConfirmWithCheckboxResult,
} from './confirmDialogContext';

// SOT-1401: アプリ内のOK/キャンセルのみの確認モーダル。
// ブラウザ標準の window.confirm() は連続表示時に「このページでこれ以上ダイアログを生成しない」
// というチェックを自動で差し込む。それを排除し、選択肢を OK / キャンセルのみにするための代替。
// SOT-1595: 任意で「関連タスクも削除する」等のチェックボックスを1つ表示できるよう拡張した。
interface DialogState {
  message: string;
  options?: ConfirmCheckboxOptions;
  checked: boolean;
  resolve: (value: boolean | ConfirmWithCheckboxResult) => void;
}

export function ConfirmDialogProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [state, setState] = useState<DialogState | null>(null);

  const confirm = useCallback(
    (message: string, options?: ConfirmCheckboxOptions) => {
      return new Promise((resolve) => {
        // 既に表示中のものがあれば「キャンセル扱い」で畳んでから新しいものを出す。
        setState((prev) => {
          if (prev) prev.resolve(prev.options ? { confirmed: false, checked: false } : false);
          return {
            message,
            options,
            checked: options?.checkbox.defaultChecked ?? false,
            resolve,
          };
        });
      });
    },
    [],
  ) as ConfirmFn;

  const close = useCallback((confirmed: boolean) => {
    setState((prev) => {
      if (prev) {
        prev.resolve(prev.options ? { confirmed, checked: prev.checked } : confirmed);
      }
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
            {state.options && (
              <label className="mt-4 flex items-start gap-2 text-sm text-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={state.checked}
                  onChange={(e) =>
                    setState((prev) => (prev ? { ...prev, checked: e.target.checked } : prev))
                  }
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-border text-brand focus:ring-brand"
                />
                <span>{state.options.checkbox.label}</span>
              </label>
            )}
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
