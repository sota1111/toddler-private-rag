import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// シナリオ e2e (SOT-1265 / 親 SOT-1258): ユーザー操作 → 画面遷移 / 表示を検証する。
// 1テスト = 1ユーザーストーリー。すべての `/api/**` はモックして決定的にする。

test.describe('toddler-private-rag シナリオ', () => {
  test('S1: 未認証で保護ページ(/data/:id 詳細)にアクセスすると /login へリダイレクトされる (SOT-1312)', async ({ page }) => {
    await installApiMocks(page, { authed: false })
    // SOT-1312: データ一覧 /data は廃止。詳細 /data/:id は引き続き保護ページ。
    await page.goto('/data/1')
    await expect(page).toHaveURL(/\/login/)
    await expect(page.locator('input[type="email"]')).toBeVisible()
  })

  test('S2: ログイン後、主要メニューを辿って各画面へ遷移できる（データメニューは廃止） (SOT-1312)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // SOT-1312: 「データ」メニューはナビゲーションから削除されている
    await expect(page.locator('nav a[href="/data"]')).toHaveCount(0)

    await page.locator('nav a[href="/info"]').first().click()
    await expect(page).toHaveURL(/\/info/)

    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await expect(page.locator('input[type="file"]')).toBeAttached()

    await page.locator('nav a[href="/"]').first().click()
    await expect(page).toHaveURL(/\/$/)
  })

  test('S3: 詳細ページ(/data/:id)はタイトルが表示される (SOT-1312)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // SOT-1312: データ一覧は廃止。詳細ページは他画面のリンク先として残存し、直接遷移でも表示できる。
    await page.goto('/data/1')
    await expect(page).toHaveURL(/\/data\/1$/)
    await expect(page.getByRole('heading', { name: '4月の給食メニュー' })).toBeVisible()
  })

  test('S5: 詳細ページで削除すると元の画面へ戻り対象が消える (SOT-1312)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)
    // confirm ダイアログを自動承認する
    page.on('dialog', dialog => dialog.accept())

    // SOT-1312: 一覧は廃止。タスク一覧メニュー経由で詳細へ遷移する。
    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)
    await page.getByRole('link', { name: /運動会のお知らせ/ }).click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()

    await page.getByRole('button', { name: '削除' }).click()
    // 削除後は遷移元（タスク一覧）へ戻り、対象が消える
    await expect(page).toHaveURL(/\/tasks/)
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)
  })

  test('S6: 写真を選んで自動登録すると本登録を介さず写真一覧(registered)に反映される', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)

    // 1x1 PNG を file input へ投入してOCR→自動登録フローを起動する
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

    // SOT-1324: 本登録を介さず直接登録された完了カードと、抽出されたタイトルが表示される
    await expect(page.getByText('アップ完了（登録しました）')).toBeVisible()
    await expect(page.getByText('お知らせ_自動登録テスト', { exact: false })).toBeVisible()

    // 「写真一覧を開く」で /registered へ遷移し、本登録された写真がタイトルで並ぶ
    await page.getByRole('button', { name: '写真一覧を開く' }).click()
    await expect(page).toHaveURL(/\/registered/)
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

  test('S9: タスク一覧メニューでカレンダー下と同じ一覧が表示され、項目から詳細へ遷移できる (SOT-1313)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)

    // タスク一覧見出しが表示される
    await expect(page.getByRole('heading', { name: 'タスク一覧' })).toBeVisible()

    // 日付つき予定（運動会のお知らせ / 2026-10-15）が一覧に表示される
    const eventLink = page.getByRole('link', { name: /運動会のお知らせ/ })
    await expect(eventLink).toBeVisible()
    await expect(page.getByText('2026-10-15')).toBeVisible()

    // SOT-1314: ステータス絞り込み。確認済みでは未対応の予定が消え、未対応で再表示される。
    await page.getByRole('button', { name: '確認済み' }).click()
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)
    await page.getByRole('button', { name: '未対応' }).click()
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toBeVisible()

    // 項目クリックで該当データ詳細へ遷移する
    await eventLink.click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()
    // SOT-1313 reopen: 詳細でタスクの内容（本文）が確認できる
    await expect(
      page.getByText('10月15日に運動会を開催します。お弁当の準備をお願いします。'),
    ).toBeVisible()
  })

  test('S10: 設定メニューで言語・標準時間・子どもの名前を設定でき、再読込後も保持される (SOT-1315)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/settings"]').first().click()
    await expect(page).toHaveURL(/\/settings/)
    await expect(page.getByRole('heading', { name: '設定' })).toBeVisible()

    // 言語・標準時間・子どもの名前のコントロールが表示される
    await expect(page.getByLabel('言語')).toBeVisible()
    await expect(page.getByLabel('標準時間（タイムゾーン）')).toBeVisible()
    await expect(page.getByLabel('子どもの名前')).toBeVisible()

    // 標準時間と子どもの名前を設定する
    await page.getByLabel('標準時間（タイムゾーン）').selectOption('America/New_York')
    await page.getByLabel('子どもの名前').fill('たろう')

    // 再読込しても設定が保持される（localStorage 永続化）
    await page.reload()
    await expect(page.getByLabel('標準時間（タイムゾーン）')).toHaveValue('America/New_York')
    await expect(page.getByLabel('子どもの名前')).toHaveValue('たろう')
  })

  test('S11: 登録一覧メニュー（仮登録の右）から本登録タイトル一覧を開き、タイトルクリックで詳細(タイトル+写真)へ遷移できる (SOT-1311)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // 登録メニューは登録ページ上で表示されるため、まず自動登録へ遷移してから「登録一覧」を開く
    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await page.locator('a[href="/registered"]').first().click()
    await expect(page).toHaveURL(/\/registered/)
    await expect(page.getByRole('heading', { name: '写真一覧' })).toBeVisible()

    // 本登録データのタイトルがリンクとして並ぶ（写真ありのレコードのみ）
    await expect(page.getByRole('link', { name: /4月の給食メニュー/ })).toBeVisible()

    // SOT-1318: タスク(予定日つき・写真なし)の「運動会のお知らせ」は登録一覧には出ない。
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)

    // タイトルをクリックすると詳細でタイトル+写真が表示される
    await page.getByRole('link', { name: /4月の給食メニュー/ }).click()
    await expect(page).toHaveURL(/\/data\/1/)
    await expect(page.getByRole('heading', { name: '4月の給食メニュー' })).toBeVisible()
    await expect(page.locator('img').first()).toBeVisible()

    // SOT-1325: 写真の下に文字起こし(OCR原文)が設定言語で表示される
    await expect(page.getByRole('heading', { name: '文字起こし' })).toBeVisible()
    await expect(page.getByText('今月の給食は和食中心です。', { exact: true })).toBeVisible()
  })
})
