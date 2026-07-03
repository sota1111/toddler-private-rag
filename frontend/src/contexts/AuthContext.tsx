import { useState, useEffect, type ReactNode } from 'react'
import { AuthContext } from './authContextValue'
import { signInWithGoogleIdToken, getGoogleRedirectIdToken } from '../firebase'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [email, setEmail] = useState<string | null>(null)

  // SOT-1487/SOT-1494: Firebase の ID トークンをバックエンドに渡し、署名付きセッション
  // cookie を発行してもらう（allowlist はサーバ側で確認）。popup / redirect 両方式で共通。
  const establishGoogleSession = async (idToken: string) => {
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

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        // SOT-1494: Safari 等で popup がブロックされ redirect にフォールバックした場合、
        // 戻ってきたこのマウント時に ID トークンを回収してセッションを確立する。
        const redirectToken = await getGoogleRedirectIdToken()
        if (redirectToken) {
          await establishGoogleSession(redirectToken)
          if (!cancelled) setLoading(false)
          return
        }
      } catch {
        // redirect 結果の処理に失敗しても、下の /me による通常判定にフォールバックする。
      }
      try {
        const res = await fetch('/api/auth/me', { credentials: 'include' })
        if (cancelled) return
        if (res.ok) {
          setIsAuthenticated(true)
        } else {
          setIsAuthenticated(false)
          setEmail(null)
        }
      } catch {
        if (cancelled) return
        setIsAuthenticated(false)
        setEmail(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
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

  // SOT-1487: Google 認証。popup で ID トークンを取得してセッションを確立する。popup が
  // 使えないブラウザ（Safari 等）では signInWithGoogleIdToken 内で redirect に切り替わり、
  // 戻ってきたマウント時に establishGoogleSession が実行される。
  const loginWithGoogle = async () => {
    const idToken = await signInWithGoogleIdToken()
    await establishGoogleSession(idToken)
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
