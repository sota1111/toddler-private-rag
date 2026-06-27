import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// シナリオ e2e (SOT-1265 / 親 SOT-1258): ユーザー操作 → 画面遷移 / 表示を検証する。
// 1テスト = 1ユーザーストーリー。すべての `/api/**` はモックして決定的にする。

test.describe('toddler-private-rag シナリオ', () => {
  test('S1: 未認証で /data にアクセスすると /login へリダイレクトされる', async ({ page }) => {
    await installApiMocks(page, { authed: false })
    await page.goto('/data')
    await expect(page).toHaveURL(/\/login/)
    await expect(page.locator('input[type="email"]')).toBeVisible()
  })

  test('S2: ログイン後、主要メニューを辿って各画面へ遷移できる', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/info"]').first().click()
    await expect(page).toHaveURL(/\/info/)

    await page.locator('nav a[href="/data"]').first().click()
    await expect(page).toHaveURL(/\/data$/)

    await page.locator('nav a[href="/memo"]').first().click()
    await expect(page).toHaveURL(/\/memo/)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await expect(page.locator('input[type="file"]')).toBeAttached()

    await page.locator('nav a[href="/"]').first().click()
    await expect(page).toHaveURL(/\/$/)
  })

  test('S3: データ一覧から行を選ぶと詳細ページへ遷移し内容が表示される', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/data"]').first().click()
    await expect(page).toHaveURL(/\/data$/)
    // 一覧に本登録済みデータが表示される
    await expect(page.getByRole('button', { name: '4月の給食メニュー' })).toBeVisible()

    await page.getByRole('button', { name: '4月の給食メニュー' }).click()
    await expect(page).toHaveURL(/\/data\/1$/)
    await expect(page.getByRole('heading', { name: '4月の給食メニュー' })).toBeVisible()
    await expect(page.getByText('今月の給食は和食中心です', { exact: false })).toBeVisible()
  })

  test('S4: 詳細ページで編集して保存すると内容が更新される', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // 認証は in-memory のため、保護ページはリロードでなくクライアント遷移で開く
    await page.locator('nav a[href="/data"]').first().click()
    await page.getByRole('button', { name: '運動会のお知らせ' }).click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()

    await page.getByRole('button', { name: '編集' }).click()
    const titleInput = page.locator('input[name="title"]')
    await expect(titleInput).toBeVisible()
    await titleInput.fill('運動会のお知らせ（更新版）')
    await page.getByRole('button', { name: '保存' }).click()

    // 保存後は表示モードに戻り、更新後タイトルが表示される
    await expect(page.getByRole('heading', { name: '運動会のお知らせ（更新版）' })).toBeVisible()
    await expect(titleInput).toHaveCount(0)
  })

  test('S5: 詳細ページで削除すると一覧へ戻り対象が消える', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)
    // confirm ダイアログを自動承認する
    page.on('dialog', dialog => dialog.accept())

    // 認証は in-memory のため、保護ページはクライアント遷移で開く
    await page.locator('nav a[href="/data"]').first().click()
    await page.getByRole('button', { name: '4月の給食メニュー' }).click()
    await expect(page).toHaveURL(/\/data\/1$/)
    await expect(page.getByRole('heading', { name: '4月の給食メニュー' })).toBeVisible()

    await page.getByRole('button', { name: '削除' }).click()
    await expect(page).toHaveURL(/\/data$/)
    // 削除した行は消え、残りの行は表示される
    await expect(page.getByRole('button', { name: '4月の給食メニュー' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '運動会のお知らせ' })).toBeVisible()
  })

  test('S6: 写真を選んで自動登録すると仮登録(drafts)に反映される', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)

    // 1x1 PNG を file input へ投入してOCR→仮登録フローを起動する
    await page.locator('input[type="file"]').setInputFiles({
      name: 'photo.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
        'base64',
      ),
    })

    // SOT-1288: 選択直後は確認画面が表示され、まだアップロードされない
    await expect(page.getByText('この写真でよろしいですか？')).toBeVisible()
    await page.getByRole('button', { name: 'この写真で登録' }).click()

    // 仮登録の完了カードと、抽出されたタイトルが表示される
    await expect(page.getByText('アップ完了（仮登録しました）')).toBeVisible()
    await expect(page.getByText('お知らせ_自動登録テスト', { exact: false })).toBeVisible()

    // 「登録ページ（仮登録一覧）を開く」で /drafts へ遷移し、登録した仮登録が並ぶ
    await page.getByRole('button', { name: '登録ページ（仮登録一覧）を開く' }).click()
    await expect(page).toHaveURL(/\/drafts/)
    await expect(page.getByText('お知らせ_自動登録テスト', { exact: false })).toBeVisible()
  })

  test('S7: 仮登録を本登録すると一覧から消える', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // 認証は in-memory のため、登録メニュー経由で仮登録一覧へクライアント遷移する
    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await page.locator('a[href="/drafts"]').first().click()
    await expect(page).toHaveURL(/\/drafts/)
    await expect(page.getByRole('heading', { name: '遠足のしおり（仮）' })).toBeVisible()

    await page.getByRole('button', { name: '本登録する' }).click()

    // 本登録後は仮登録一覧から消え、空表示になる
    await expect(page.getByRole('heading', { name: '遠足のしおり（仮）' })).toHaveCount(0)
    await expect(
      page.getByText('仮登録はありません。自動登録から写真をアップすると、ここに表示されます。'),
    ).toBeVisible()
  })

  test('S8: 予定画面でカレンダーと日付つき予定一覧が表示され、項目から詳細へ遷移できる (SOT-1306)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/schedule"]').first().click()
    await expect(page).toHaveURL(/\/schedule/)

    // カレンダー見出しと予定一覧見出しが表示される
    await expect(page.getByRole('heading', { name: '予定カレンダー' })).toBeVisible()
    await expect(page.getByText('予定一覧')).toBeVisible()

    // 日付つき予定（運動会のお知らせ / 2026-10-15）が一覧に表示される
    const eventLink = page.getByRole('link', { name: /運動会のお知らせ/ })
    await expect(eventLink).toBeVisible()
    await expect(page.getByText('2026-10-15')).toBeVisible()

    // 項目クリックで該当データ詳細へ遷移する
    await eventLink.click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()
  })
})
