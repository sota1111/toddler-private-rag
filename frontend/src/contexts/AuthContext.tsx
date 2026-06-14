import { useState, useEffect, type ReactNode } from 'react'
import { signInWithEmailAndPassword, signOut } from 'firebase/auth'
import { auth } from '../lib/firebase'
import { AuthContext } from './authContextValue'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [email, setEmail] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(res => {
        if (res.ok) {
          setIsAuthenticated(true)
        } else {
          setIsAuthenticated(false)
          setEmail(null)
        }
      })
      .catch(() => {
        setIsAuthenticated(false)
        setEmail(null)
      })
  }, [])

  const login = async (emailAddr: string, password: string) => {
    const credential = await signInWithEmailAndPassword(auth, emailAddr, password)
    const idToken = await credential.user.getIdToken()
    const res = await fetch('/api/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ idToken }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail ?? '認証に失敗しました')
    }
    setIsAuthenticated(true)
    setEmail(emailAddr)
  }

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    await signOut(auth)
    setIsAuthenticated(false)
    setEmail(null)
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, email, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
