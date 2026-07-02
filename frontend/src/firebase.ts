// SOT-1487: Google サインイン用の Firebase 初期化。
//
// 初期化は loginWithGoogle が呼ばれたときだけ遅延実行する。VITE_FIREBASE_* が
// 未設定でもモジュール読み込みやアプリ描画は壊れず、ボタンを押したときだけエラーになる。
import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, signInWithPopup } from 'firebase/auth'

let app: FirebaseApp | null = null

function getFirebaseAuth() {
  const apiKey = import.meta.env.VITE_FIREBASE_API_KEY as string | undefined
  const authDomain = import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined
  const projectId = import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined

  if (!apiKey || !authDomain) {
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
