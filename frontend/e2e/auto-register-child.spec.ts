import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// SOT-1604: 「続けて登録すると子どもの選択ができない」の回帰テスト。
// お子さま一覧の取得を遅延させ、別画面から自動登録へ戻った直後（取得完了前）に写真を選んでも、
// 確認画面に子ども選択が出ることを確認する。react-query の ['children'] キャッシュ共有で、
// 再マウントでも即座に一覧が使えるため、確認画面に必ず子ども選択が出る。
test('SOT-1604: child selector shows on re-entry even before children refetch resolves', async ({ page }) => {
  const kids = [{ id: 1, name: 'たろう', created_at: '2026-01-01T00:00:00Z' }]
  await installApiMocks(page, { authed: true, children: kids })
  // 初回 GET は即応答（=キャッシュ populate）、以降の再取得は 1500ms 遅延させる。
  // これで「初回登録は成功→キャッシュ済み、再入場の refetch は遅い」実挙動を再現する。
  let childrenCalls = 0
  await page.route('**/api/children', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    childrenCalls += 1
    if (childrenCalls > 1) await new Promise((r) => setTimeout(r, 1500))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(kids),
    })
  })

  await login(page)
  await page.goto('/create/auto')

  const fileInput = page.locator('input[type="file"]')

  // 初回はお子さま選択が出る（=children がキャッシュに載る）ことを確認してから進む。
  await page.getByRole('button', { name: '写真やPDFを選択して自動入力' }).click()
  await fileInput.setInputFiles({ name: 'first.png', mimeType: 'image/png', buffer: Buffer.from([137, 80, 78, 71]) })
  await expect(page.getByText('この写真でよろしいですか？')).toBeVisible()
  await expect(page.getByRole('combobox')).toBeVisible()
  await page.getByRole('button', { name: 'この写真で登録' }).click()
  await expect(page.getByRole('button', { name: '続けて写真をアップ' })).toBeVisible()

  // 別画面へ移動してから自動登録へ戻る（=再マウントで children 再取得が走る）。
  await page.getByRole('link', { name: '仮登録' }).first().click()
  await expect(page).toHaveURL(/\/drafts/)
  await page.getByRole('link', { name: '自動登録' }).first().click()
  await expect(page).toHaveURL(/\/create\/auto/)

  // children 再取得の完了を待たずに写真を選ぶ。
  await page.getByRole('button', { name: '写真やPDFを選択して自動入力' }).click()
  await fileInput.setInputFiles({ name: 'a.png', mimeType: 'image/png', buffer: Buffer.from([137, 80, 78, 71]) })
  await expect(page.getByText('この写真でよろしいですか？')).toBeVisible()

  // 子ども選択が確認画面に即座に出ているべき（キャッシュから供給）。
  await expect(page.getByRole('combobox')).toBeVisible({ timeout: 1000 })
  await expect(page.getByRole('option', { name: 'たろう' })).toBeAttached()
})

// 続けてアップ（同一画面で resetForAnother）でも子ども選択が出続けることの確認。
test('SOT-1604: child selector persists across consecutive uploads on the same page', async ({ page }) => {
  const kids = [{ id: 1, name: 'たろう', created_at: '2026-01-01T00:00:00Z' }]
  await installApiMocks(page, { authed: true, children: kids })
  await login(page)
  await page.goto('/create/auto')

  const fileInput = page.locator('input[type="file"]')

  // 1回目
  await page.getByRole('button', { name: '写真やPDFを選択して自動入力' }).click()
  await fileInput.setInputFiles({ name: 'a.png', mimeType: 'image/png', buffer: Buffer.from([137, 80, 78, 71]) })
  await expect(page.getByText('この写真でよろしいですか？')).toBeVisible()
  await expect(page.getByRole('combobox')).toBeVisible()
  await page.getByRole('button', { name: 'この写真で登録' }).click()
  await page.getByRole('button', { name: '続けて写真をアップ' }).click()

  // 2回目
  await page.getByRole('button', { name: '写真やPDFを選択して自動入力' }).click()
  await fileInput.setInputFiles({ name: 'b.png', mimeType: 'image/png', buffer: Buffer.from([137, 80, 78, 71]) })
  await expect(page.getByText('この写真でよろしいですか？')).toBeVisible()
  await expect(page.getByRole('combobox')).toBeVisible()
})
