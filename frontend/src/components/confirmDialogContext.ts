import { createContext, useContext } from 'react';

// SOT-1401: OK/キャンセルのみの確認モーダルの context。
// component と分離しておくことで fast-refresh / only-export-components 制約を満たす
// （i18n の i18nContextValue.ts と同じ構成）。
export type ConfirmFn = (message: string) => Promise<boolean>;

export const ConfirmContext = createContext<ConfirmFn>(() => Promise.resolve(false));

export function useConfirm(): ConfirmFn {
  return useContext(ConfirmContext);
}
