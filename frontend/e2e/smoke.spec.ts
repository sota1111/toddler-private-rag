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

// ログインフォームから認証してダッシュボードに遷移する（このアプリは auth/me 解決前に
// /login へ一度バウンスするため、実フローでログインするのが最も確実）。
async function login(page: Page) {
  await page.goto('/login')
  await page.locator('input[type="email"]').fill('test@example.com')
  await page.locator('input[type="password"]').fill('password123')
  await page.locator('button[type="submit"]').click()
  // 認証後はボトムナビ（登録リンク）が表示される。
  await expect(page.locator('a[href="/create/auto"]')).toBeVisible()
}

test('未認証で / にアクセスすると /login へリダイレクトしフォームが表示される', async ({ page }) => {
  await mockApi(page, { authed: false })
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await expect(page.locator('input[type="password"]')).toBeVisible()
})

test('/login がメール・パスワード入力と送信ボタンを表示する', async ({ page }) => {
  await mockApi(page, { authed: false })
  await page.goto('/login')
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await expect(page.locator('input[type="password"]')).toBeVisible()
  await expect(page.locator('button[type="submit"]')).toBeVisible()
})

test('ログインフローでダッシュボードへ遷移しボトムナビが表示される', async ({ page }) => {
  await mockApi(page, { authed: true })
  await login(page)
  await expect(page).not.toHaveURL(/\/login/)
  // ボトムナビの主要リンクが揃う。
  await expect(page.locator('a[href="/"]')).toBeVisible()
  await expect(page.locator('a[href="/info"]')).toBeVisible()
})

test('登録メニューへ遷移すると写真アップロードの file input が表示される', async ({ page }) => {
  await mockApi(page, { authed: true })
  await login(page)
  await page.locator('a[href="/create/auto"]').click()
  await expect(page).toHaveURL(/\/create\/auto/)
  await expect(page.locator('input[type="file"]')).toBeAttached()
})
