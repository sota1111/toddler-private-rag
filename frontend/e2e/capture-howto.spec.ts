import { test } from '@playwright/test'
import fs from 'node:fs'
import { installApiMocks, login } from './support/mockApi'

// SOT-1435: 使い方画面(/howto)に載せる各主要画面のスクショを生成する。
// 既存のモックハーネス(installApiMocks + login)を流用し、public/howto/*.png に保存する。
// 保存先はフロントエンドの静的配信ディレクトリなので、生成した PNG をコミットすると
// アプリ内の HowToPage が `/howto/<file>.png` として表示できる。
const OUT = 'public/howto'

test('capture how-to screenshots', async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true })
  await installApiMocks(page)
  await login(page)
  const shots: Array<[string, string]> = [
    ['/create/auto', 'register.png'],
    ['/tasks', 'tasks.png'],
    ['/schedule', 'schedule.png'],
    ['/', 'board.png'],
    ['/info?tab=ask', 'ask.png'],
    ['/settings', 'settings.png'],
  ]
  for (const [route, file] of shots) {
    await page.goto(route)
    await page.waitForTimeout(600)
    await page.screenshot({ path: `${OUT}/${file}`, fullPage: true })
  }
})
