import { createContext } from 'react'

export interface AuthContextType {
  isAuthenticated: boolean
  loading: boolean
  email: string | null
  login: (email: string, password: string) => Promise<void>
  loginWithGoogle: () => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  loading: true,
  email: null,
  login: async () => {},
  loginWithGoogle: async () => {},
  logout: () => {},
})
