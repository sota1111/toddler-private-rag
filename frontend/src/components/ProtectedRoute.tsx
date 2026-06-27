import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/useAuth'
import { useI18n } from '../i18n/useI18n'
import type { ReactNode } from 'react'

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, loading } = useAuth()
  const { t } = useI18n()

  // 認証確認（/api/auth/me）が解決するまではリダイレクトせず、機能も描画しない。
  // 解決前に /login へバウンスすると、有効なセッションがあってもリロードで
  // ログイン画面に戻ってしまうため（SOT-1302）。
  if (loading) {
    return (
      <div className="flex justify-center py-16 text-muted-foreground text-sm" aria-busy="true">
        {t('common.loading')}
      </div>
    )
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}
