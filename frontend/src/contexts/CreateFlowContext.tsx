import { useState, type ReactNode } from 'react'
import { CreateFlowContext, type StagedRegistration } from './createFlowContextValue'

// 一時登録（写真アップ/手入力）→ 一時登録確認 → 登録情報確認 の各ページで
// 入力内容と添付ファイルを保持するプロバイダ。
export function CreateFlowProvider({ children }: { children: ReactNode }) {
  const [staged, setStaged] = useState<StagedRegistration | null>(null)
  const clear = () => setStaged(null)

  return (
    <CreateFlowContext.Provider value={{ staged, setStaged, clear }}>
      {children}
    </CreateFlowContext.Provider>
  )
}
