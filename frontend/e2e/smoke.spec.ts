import { test, expect, type Page } from '@playwright/test'

// バックエンドは起動しない。すべての `/api/**` をブラウザ層で横取りし決定的なレスポンスを返す（SOT-1154）。
// authed=false で /auth/me を 401 にすると ProtectedRoute が /login へリダイレクトする。
async function mockApi(page: Page, opts: { authed: boolean }) {
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/auth/me')) {
      await route.fulfill({ status: opts.authed ? 200 : 401, contentType: 'application/json', body: '{}' })
      return
    }
    if (pathname.endsWith('/auth/session') || pathname.endsWith('/auth/logout')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    // info 系のリスト/フィードはすべて空配列。DashboardPage は `data ?? []` でガード済み。
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
}

// ログインフォームから認証してダッシュボードに遷移する。
async function login(page: Page) {
  await page.goto('/login')
  // 方式選択画面で「メールアドレスでログイン」を選ぶとフォームが表示される。
  await page.getByRole('button', { name: 'メールアドレスでログイン' }).click()
  await page.locator('input[type="email"]').fill('test@example.com')
  await page.locator('input[type="password"]').fill('password123')
  await page.locator('button[type="submit"]').click()
  // 認証後はボトムナビ（登録リンク）が表示される。
  await expect(page.locator('a[href="/create/auto"]')).toBeVisible()
}

test('未認証で / にアクセスすると /login へリダイレクトし方式選択が表示される', async ({ page }) => {
  await mockApi(page, { authed: false })
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  // 方式選択画面: メール/Google の2択が表示される。
  await expect(page.getByRole('button', { name: 'メールアドレスでログイン' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Googleでログイン' })).toBeVisible()
  // 選択前はメール入力フォームは表示されない。
  await expect(page.locator('input[type="email"]')).toHaveCount(0)
})

test('/login でメール方式を選ぶとメール・パスワード入力と送信ボタンを表示する', async ({ page }) => {
  await mockApi(page, { authed: false })
  await page.goto('/login')
  await page.getByRole('button', { name: 'メールアドレスでログイン' }).click()
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await expect(page.locator('input[type="password"]')).toBeVisible()
  await expect(page.locator('button[type="submit"]')).toBeVisible()
})

test('ログインフローでダッシュボードへ遷移しボトムナビが表示される', async ({ page }) => {
  // 未認証(/auth/me=401)から開始し、ログインフォームを実際に操作して認証する。
  await mockApi(page, { authed: false })
  await login(page)
  await expect(page).not.toHaveURL(/\/login/)
  // ボトムナビの主要リンクが揃う。
  await expect(page.locator('a[href="/"]')).toBeVisible()
  await expect(page.locator('a[href="/info"]')).toBeVisible()
})

test('有効なセッションがあればリロード相当の直接アクセスでもログイン画面に戻らない (SOT-1302)', async ({ page }) => {
  // authed=true（= /auth/me が 200 = リロード後にセッションが復元される状態）で
  // 保護ページへ直接アクセスしても /login へバウンスせず、その画面に留まる。
  await mockApi(page, { authed: true })
  // SOT-1312: データ一覧 /data は廃止。詳細 /data/:id は保護ページとして残存する。
  await page.goto('/data/1')
  await expect(page).not.toHaveURL(/\/login/)
  await expect(page.locator('a[href="/create/auto"]')).toBeVisible()
})

test('認証済みで /login に着地したらダッシュボードへリダイレクトする (SOT-1508)', async ({ page }) => {
  // Google の redirect 方式ログインでは認証後アプリに戻ると /login に着地し、
  // AuthProvider がセッションを復元して認証済みになる（= /auth/me 200 相当）。
  // このとき /login に留まらず / へ遷移し、ログイン画面ではなく本体を表示する。
  await mockApi(page, { authed: true })
  await page.goto('/login')
  await expect(page).not.toHaveURL(/\/login/)
  // ログインフォーム（方式選択ボタン）ではなく認証後のナビが表示される。
  await expect(page.getByRole('button', { name: 'メールアドレスでログイン' })).toHaveCount(0)
  await expect(page.locator('a[href="/create/auto"]')).toBeVisible()
})

test('ログイン前はタイトルと言語切替のみ表示される (SOT-1302)', async ({ page }) => {
  await mockApi(page, { authed: false })
  await page.goto('/login')
  await expect(page).toHaveURL(/\/login/)
  // タイトルと言語切替（JP/EN）は表示される。
  await expect(page.getByText('おたよりナビ', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'JP' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'EN' })).toBeVisible()
  // 認証後のみのナビ（登録リンク）は表示されない。
  await expect(page.locator('a[href="/create/auto"]')).toHaveCount(0)
})

test('登録メニューへ遷移すると写真アップロードの file input が表示される', async ({ page }) => {
  // 未認証から開始し、ログインフォームを操作して認証したうえで登録メニューへ遷移する。
  await mockApi(page, { authed: false })
  await login(page)
  await page.locator('a[href="/create/auto"]').click()
  await expect(page).toHaveURL(/\/create\/auto/)
  await expect(page.locator('input[type="file"]')).toBeAttached()
})
