import { createContext } from 'react'

export interface AuthContextType {
  isAuthenticated: boolean
  email: string | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  email: null,
  login: async () => {},
  logout: () => {},
})
