import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/useAuth'
import { useI18n } from '../i18n/useI18n'

type LoginMethod = 'select' | 'email'

export default function LoginPage() {
  const { login, loginWithGoogle } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [method, setMethod] = useState<LoginMethod>('select')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : ''
      setError(msg || t('login.failed'))
    } finally {
      setLoading(false)
    }
  }

  const handleGoogle = async () => {
    setError('')
    setLoading(true)
    try {
      await loginWithGoogle()
      navigate('/')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : ''
      setError(msg || t('login.failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-start justify-center bg-surface-muted pt-24 sm:pt-32">
      <div className="max-w-md w-full space-y-8 p-8 bg-surface rounded-lg shadow">
        <h2 className="text-2xl font-bold text-center text-foreground">{t('login.title')}</h2>

        {method === 'select' ? (
          <div className="space-y-4">
            {error && <p className="text-red-500 text-sm">{error}</p>}
            <button
              type="button"
              onClick={() => {
                setError('')
                setMethod('email')
              }}
              disabled={loading}
              className="w-full bg-brand text-white py-2 px-4 rounded-md hover:bg-brand-strong disabled:opacity-50"
            >
              {t('login.methodEmail')}
            </button>
            {/* SOT-1495: Google 公式 [Sign in with Google] ブランディングに準拠したボタン。
                認証フロー自体は既存の Firebase popup/redirect（handleGoogle）をそのまま利用し、
                見た目のみ公式仕様（白背景・#747775 枠・4色 Google ロゴ・Roboto Medium 相当）に合わせる。 */}
            <button
              type="button"
              onClick={handleGoogle}
              disabled={loading}
              aria-label={t('login.google')}
              className="w-full inline-flex items-center justify-center gap-3 h-10 px-3 bg-white border border-[#747775] rounded font-medium text-sm text-[#1f1f1f] hover:bg-[#f2f2f2] focus:outline-none focus:ring-2 focus:ring-[#4285f4] disabled:opacity-50"
            >
              <svg
                aria-hidden="true"
                width="18"
                height="18"
                viewBox="0 0 48 48"
                className="shrink-0"
              >
                <path
                  fill="#EA4335"
                  d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
                />
                <path
                  fill="#4285F4"
                  d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
                />
                <path
                  fill="#FBBC05"
                  d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
                />
                <path
                  fill="#34A853"
                  d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
                />
                <path fill="none" d="M0 0h48v48H0z" />
              </svg>
              <span>{t('login.google')}</span>
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-foreground">{t('login.email')}</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                className="mt-1 block w-full border border-border rounded-md px-3 py-2 text-foreground bg-surface focus:outline-none focus:ring-brand focus:border-brand"
                placeholder="your-email@example.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground">{t('login.password')}</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                className="mt-1 block w-full border border-border rounded-md px-3 py-2 text-foreground bg-surface focus:outline-none focus:ring-brand focus:border-brand"
              />
            </div>
            {error && <p className="text-red-500 text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-brand text-white py-2 px-4 rounded-md hover:bg-brand-strong disabled:opacity-50"
            >
              {loading ? t('login.submitting') : t('login.submit')}
            </button>
            <button
              type="button"
              onClick={() => {
                setError('')
                setMethod('select')
              }}
              disabled={loading}
              className="w-full text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              {t('login.back')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
