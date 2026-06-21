import { useContext } from 'react'
import { RoleContext } from './roleContextValue'

export function useRole() {
  return useContext(RoleContext)
}
