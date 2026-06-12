import { createContext } from 'react'

export const TOKEN_KEY = 'auth_token'

export interface AuthContextType {
  isAuthenticated: boolean
  username: string | null
  login: (user: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  username: null,
  login: async () => {},
  logout: () => {},
})
