import { createContext } from 'react'

export type Role = 'admin' | 'user'

export interface RoleContextType {
  role: Role
  setRole: (role: Role) => void
}

export const RoleContext = createContext<RoleContextType>({
  role: 'user',
  setRole: () => {},
})
