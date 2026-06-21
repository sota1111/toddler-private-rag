import { useState, useCallback, type ReactNode } from 'react'
import { RoleContext, type Role } from './roleContextValue'

const STORAGE_KEY = 'tpr.role'

function getInitialRole(): Role {
  if (typeof window === 'undefined') return 'user'
  const saved = window.localStorage.getItem(STORAGE_KEY)
  return saved === 'admin' || saved === 'user' ? saved : 'user'
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role>(getInitialRole)

  const setRole = useCallback((next: Role) => {
    setRoleState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* localStorage unavailable — keep in-memory only */
    }
  }, [])

  return (
    <RoleContext.Provider value={{ role, setRole }}>
      {children}
    </RoleContext.Provider>
  )
}
