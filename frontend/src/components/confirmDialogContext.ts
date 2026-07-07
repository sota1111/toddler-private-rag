import { createContext, useContext } from 'react';

// SOT-1401: OK/キャンセルのみの確認モーダルの context。
// component と分離しておくことで fast-refresh / only-export-components 制約を満たす
// （i18n の i18nContextValue.ts と同じ構成）。
//
// SOT-1595: 写真削除時に「関連タスクも削除する」チェックボックスを同じ確認モーダルで扱えるよう、
// 任意の checkbox オプションを受け取れるよう拡張した。オプション無しの呼び出しは従来どおり
// Promise<boolean> を返すため、既存の `if (await confirm(msg))` 呼び出しは一切変更不要。
export interface ConfirmCheckboxOptions {
  checkbox: {
    label: string;
    defaultChecked?: boolean;
  };
}

export interface ConfirmWithCheckboxResult {
  confirmed: boolean;
  checked: boolean;
}

export interface ConfirmFn {
  (message: string): Promise<boolean>;
  (message: string, options: ConfirmCheckboxOptions): Promise<ConfirmWithCheckboxResult>;
}

export const ConfirmContext = createContext<ConfirmFn>((() => Promise.resolve(false)) as ConfirmFn);

export function useConfirm(): ConfirmFn {
  return useContext(ConfirmContext);
}
