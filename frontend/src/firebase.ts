// SOT-1487: Google サインイン用の Firebase 初期化。
//
// 初期化は loginWithGoogle が呼ばれたときだけ遅延実行する。VITE_FIREBASE_* が
// 未設定でもモジュール読み込みやアプリ描画は壊れず、ボタンを押したときだけエラーになる。
import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
} from 'firebase/auth'

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

// SOT-1494: Safari など、ユーザー操作から少しでも非同期に離れると signInWithPopup を
// ブロックするブラウザがある（`auth/popup-blocked`）。ポップアップが使えないケースでは
// リダイレクト方式にフォールバックする。redirect はページ遷移するため、戻ってきたときに
// getGoogleRedirectIdToken() で結果を回収する（AuthContext のマウント時に呼ぶ）。
function isPopupUnavailableError(err: unknown): boolean {
  const code = (err as { code?: string } | null)?.code
  return (
    code === 'auth/popup-blocked' ||
    code === 'auth/cancelled-popup-request' ||
    code === 'auth/operation-not-supported-in-this-environment'
  )
}

// SOT-1494: モバイルブラウザは signInWithPopup を「新しいタブ」として開く。認証後にその
// タブを確実に閉じて元タブへ戻せないため、ユーザーがログイン済みの新規タブに取り残され、
// 元タブが放置される（＝「ログイン後に別の新規タブに移動している」）。popup がブロック
// されるわけではないので isPopupUnavailableError のフォールバックも発火しない。Firebase
// 公式推奨に従い、モバイルでは最初から同一タブ遷移の signInWithRedirect を使う。
function shouldUseRedirect(): boolean {
  if (typeof navigator === 'undefined') return false
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
}

/** Google サインインを行い、Firebase の ID トークンを返す。 */
export async function signInWithGoogleIdToken(): Promise<string> {
  const auth = getFirebaseAuth()
  const provider = new GoogleAuthProvider()
  // モバイルでは popup が新規タブ化して取り残されるため、同一タブの redirect を使う。
  // ページ遷移するのでこの Promise は解決せず、戻ってきたマウント時に結果を回収する。
  if (shouldUseRedirect()) {
    await signInWithRedirect(auth, provider)
    return await new Promise<string>(() => {})
  }
  try {
    const result = await signInWithPopup(auth, provider)
    return await result.user.getIdToken()
  } catch (err) {
    if (isPopupUnavailableError(err)) {
      // リダイレクトに切り替える。ここでページ遷移するのでこの Promise は解決しない。
      await signInWithRedirect(auth, provider)
      return await new Promise<string>(() => {})
    }
    throw err
  }
}

/**
 * リダイレクト方式でサインインした後にアプリへ戻ってきたときの ID トークンを回収する。
 * リダイレクト結果が無い（通常のページ読み込み）場合や Google 認証が未設定の場合は null。
 */
export async function getGoogleRedirectIdToken(): Promise<string | null> {
  // apiKey 未設定ならリダイレクト結果もあり得ないので Firebase を初期化せず抜ける。
  if (!import.meta.env.VITE_FIREBASE_API_KEY) return null
  const auth = getFirebaseAuth()
  const result = await getRedirectResult(auth)
  if (!result?.user) return null
  return await result.user.getIdToken()
}
