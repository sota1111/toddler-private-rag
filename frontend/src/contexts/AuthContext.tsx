import { useState, useEffect, type ReactNode } from 'react'
import { AuthContext } from './authContextValue'
import { signInWithGoogleIdToken } from '../firebase'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)
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
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const login = async (emailAddr: string, password: string) => {
    const res = await fetch('/api/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email: emailAddr, password }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail ?? '認証に失敗しました')
    }
    setIsAuthenticated(true)
    setEmail(emailAddr)
  }

  // SOT-1487: Google 認証。Firebase の ID トークンをバックエンドに渡し、既存の
  // 署名付きセッション cookie を発行してもらう（allowlist はサーバ側で確認）。
  const loginWithGoogle = async () => {
    const idToken = await signInWithGoogleIdToken()
    const res = await fetch('/api/auth/session/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ id_token: idToken }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      throw new Error(data.detail ?? '認証に失敗しました')
    }
    setIsAuthenticated(true)
    setEmail(data.email ?? null)
  }

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    setIsAuthenticated(false)
    setEmail(null)
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, loading, email, login, loginWithGoogle, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
