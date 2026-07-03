// SOT-1487: Google サインイン用の Firebase 初期化。
//
// 初期化は loginWithGoogle が呼ばれたときだけ遅延実行する。VITE_FIREBASE_* が
// 未設定でもモジュール読み込みやアプリ描画は壊れず、ボタンを押したときだけエラーになる。
import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, signInWithPopup } from 'firebase/auth'

let app: FirebaseApp | null = null

function getFirebaseAuth() {
  const apiKey = import.meta.env.VITE_FIREBASE_API_KEY as string | undefined
  const configuredAuthDomain = import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined
  const projectId = import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined

  if (!apiKey) {
    throw new Error('Google認証が未設定です（VITE_FIREBASE_* を設定してください）')
  }

  // SOT-1494: signInWithPopup が `auth/missing-initial-state` で失敗する問題への対処。
  // アプリは Cloud Run 独自ドメイン（*.run.app）で配信されるが、authDomain が別ドメインの
  // *.firebaseapp.com のままだと、ポップアップの認証ハンドラ（firebaseapp.com/__/auth/handler）
  // がブラウザのストレージ分離（Safari ITP / Chrome storage partitioning）下でアプリ側の
  // sessionStorage を参照できず missing-initial-state になる。
  // Firebase 公式推奨の self-hosting に従い authDomain をアプリ自身のオリジンにする。nginx が
  // /__/auth/ と /__/firebase/ を本来の firebaseapp.com へリバースプロキシするため、ハンドラは
  // アプリと同一オリジンで動作し、状態を共有できるようになる（VITE_FIREBASE_AUTH_DOMAIN は
  // nginx 側プロキシ先の設定にのみ使い、ここでは fallback として保持）。
  const authDomain =
    typeof window !== 'undefined' && window.location?.host
      ? window.location.host
      : configuredAuthDomain

  if (!authDomain) {
    throw new Error('Google認証が未設定です（VITE_FIREBASE_* を設定してください）')
  }

  if (!app) {
    app = getApps()[0] ?? initializeApp({ apiKey, authDomain, projectId })
  }
  return getAuth(app)
}

/** Google サインインを行い、Firebase の ID トークンを返す。 */
export async function signInWithGoogleIdToken(): Promise<string> {
  const auth = getFirebaseAuth()
  const provider = new GoogleAuthProvider()
  const result = await signInWithPopup(auth, provider)
  return await result.user.getIdToken()
}
