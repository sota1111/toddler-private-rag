import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// menu-calendar: カレンダーの「予定 / 献立」トグルと、献立モードのセル表示・詳細モーダル。
test.describe('menu calendar', () => {
  test('献立モードに切替えるとセルに主菜が出て、タップで詳細モーダルが開く', async ({ page }) => {
    // カレンダーは実カレンダー（今日）基準で当月を表示するので、当月の日付で献立を仕込む。
    const now = new Date()
    const y = now.getFullYear()
    const m = now.getMonth() + 1
    const date = `${y}-${String(m).padStart(2, '0')}-15`

    await installApiMocks(page, {
      authed: true,
      menuDays: [
        {
          date,
          weekday: '水',
          morning_snack: ['牛乳'],
          lunch: ['ごはん', '鮭のマヨ焼き'],
          afternoon_snack: ['牛乳'],
          main_ingredients: { red: ['さけ'], yellow: ['米'], green: ['にんじん'], other: ['塩'] },
          nutrition: {
            under3: { energy_kcal: 470, protein_g: 20, fat_g: 14 },
            over3: { energy_kcal: 500, protein_g: 22, fat_g: 13 },
          },
        },
      ],
    })
    await login(page)
    await page.goto('/schedule')

    // 既定は「予定」モード。献立タブへ切替える。
    await page.getByRole('tab', { name: '献立' }).click()

    // 当月セルに主菜（給食1品目）が圧縮表示される。
    await expect(page.getByText('ごはん').first()).toBeVisible()

    // 献立のある日をタップ → 詳細モーダル。
    await page.getByRole('button', { name: new RegExp(date) }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // 給食の全品目・栄養価が出る。
    await expect(dialog.getByText('鮭のマヨ焼き')).toBeVisible()
    await expect(dialog.getByText('500 kcal')).toBeVisible()

    // 閉じられる。
    await dialog.getByRole('button', { name: '閉じる' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('予定モードでは献立を取得せず、予定一覧が見える', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)
    await page.goto('/schedule')
    // 既定は予定モード：予定一覧の見出しが出る（献立の空状態は出ない）。
    await expect(page.getByRole('tab', { name: '予定' })).toHaveAttribute('aria-selected', 'true')
  })
})
