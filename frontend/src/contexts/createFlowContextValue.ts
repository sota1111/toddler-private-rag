import { createContext } from 'react'
import type { NurseryInfoCreate } from '../types'

// 一時登録中の入力内容と添付ファイル(File[])をcreate系ルート間で共有するためのコンテキスト値。
// 非コンポーネントの export は react-refresh lint 対策で .ts に置く（AuthContext と同じ分割）。
export interface StagedRegistration {
  data: NurseryInfoCreate
  files: File[]
}

export interface CreateFlowContextValue {
  staged: StagedRegistration | null
  setStaged: (staged: StagedRegistration | null) => void
  clear: () => void
}

export const CreateFlowContext = createContext<CreateFlowContextValue | undefined>(undefined)
