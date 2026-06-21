import { useContext } from 'react'
import { CreateFlowContext, type CreateFlowContextValue } from './createFlowContextValue'

export function useCreateFlow(): CreateFlowContextValue {
  const ctx = useContext(CreateFlowContext)
  if (!ctx) {
    throw new Error('useCreateFlow must be used within a CreateFlowProvider')
  }
  return ctx
}
