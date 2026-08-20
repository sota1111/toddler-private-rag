import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// menu-calendar: カレンダーの「予定 / 献立」トグルと、献立モードのセル表示・詳細モーダル。
test.describe('menu calendar', () => {
  test('献立モードに切替えるとセルに主菜が出て、タップで詳細モーダルが開く', async ({ page }) => {
    // カレンダーは実カレンダー（今日）基準で当月を表示するので、当月の日付で献立を仕込む。
    const now = new Date()
    const y = now.getFullYear()
    const m = now.getMonth() + 1
    const dstr = (d: number) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    const date = dstr(15)

    await installApiMocks(page, {
      authed: true,
      menuDays: [
        {
          // 魚の日: 赤列の主菜たんぱく源=さけ（牛乳はスキップ）。
          date,
          weekday: '水',
          morning_snack: ['牛乳'],
          lunch: ['ごはん', '鮭のマヨ焼き'],
          afternoon_snack: ['牛乳'],
          main_ingredients: { red: ['牛乳', 'さけ'], yellow: ['米'], green: ['にんじん'], other: ['塩'] },
          nutrition: {
            under3: { energy_kcal: 470, protein_g: 20, fat_g: 14 },
            over3: { energy_kcal: 500, protein_g: 22, fat_g: 13 },
          },
        },
        {
          // 肉の日: 赤列=豚もも。
          date: dstr(10),
          weekday: '月',
          lunch: ['ごはん', '豚のしょうが焼き'],
          main_ingredients: { red: ['豚もも', '油あげ'], yellow: ['米'], green: [], other: [] },
          nutrition: {},
        },
        {
          // 豆の日: 赤列=豆腐。
          date: dstr(20),
          weekday: '木',
          lunch: ['ごはん', '麻婆豆腐'],
          main_ingredients: { red: ['牛乳', '豆腐'], yellow: ['米'], green: [], other: [] },
          nutrition: {},
        },
      ],
    })
    await login(page)
    await page.goto('/schedule')

    // 既定は「予定」モード。献立タブへ切替える。
    await page.getByRole('tab', { name: '献立' }).click()

    // SOT-2746: セルには給食の主菜「料理名」が出る（たんぱく源の食材名ではない）。
    await expect(page.getByRole('button', { name: new RegExp(dstr(10)) })).toContainText('豚のしょうが焼き')
    await expect(page.getByRole('button', { name: new RegExp(date) })).toContainText('鮭のマヨ焼き')
    await expect(page.getByRole('button', { name: new RegExp(dstr(20)) })).toContainText('麻婆豆腐')
    // 肉/魚/豆のアイコンが主菜のたんぱく源から判定されて出る（ご飯🍚は出さない）。
    await expect(page.getByRole('button', { name: new RegExp(dstr(10)) })).toContainText('🍖')
    await expect(page.getByRole('button', { name: new RegExp(date) })).toContainText('🐟')
    await expect(page.getByRole('button', { name: new RegExp(dstr(20)) })).toContainText('🫘')
    await expect(page.getByRole('button', { name: new RegExp(dstr(10)) })).not.toContainText('🍚')

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

  test('登録アレルゲンが献立に含まれる日はカレンダーに注意が出て、詳細でアレルゲンが分かる', async ({ page }) => {
    const now = new Date()
    const y = now.getFullYear()
    const m = now.getMonth() + 1
    const dstr = (d: number) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    const date = dstr(12)

    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: '2026-01-01T00:00:00Z' }],
      // 乳アレルギーを登録。献立の「チーズ」が該当する。
      careProfiles: [
        { id: 1, child_id: '7', allergens: ['milk'], care_categories: [], created_at: '2026-01-01T00:00:00Z' },
      ],
      menuDays: [
        {
          date,
          weekday: '金',
          lunch: ['ごはん', 'チーズオムレツ'],
          morning_snack: [],
          afternoon_snack: [],
          main_ingredients: { red: ['チーズ', '卵'], yellow: ['米'], green: [], other: [] },
          nutrition: {},
        },
      ],
    })
    await login(page)
    await page.goto('/schedule')
    await page.getByRole('tab', { name: '献立' }).click()

    // 該当日のセルにアレルギー注意（⚠️）が出る。
    const cell = page.getByRole('button', { name: new RegExp(date) })
    await expect(cell).toContainText('⚠️')

    // 詳細モーダルに「アレルギー注意」と、登録済みの乳（強調）が出る。
    await cell.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('アレルギー注意')).toBeVisible()
    await expect(dialog).toContainText('乳')
  })

  test('予定モードでは献立を取得せず、予定一覧が見える', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)
    await page.goto('/schedule')
    // 既定は予定モード：予定一覧の見出しが出る（献立の空状態は出ない）。
    await expect(page.getByRole('tab', { name: '予定' })).toHaveAttribute('aria-selected', 'true')
  })
})
