import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// SOT-2736: /ask の回答に責任境界・免責（サービス=支援 / 最終判断=保護者 / 専門判断=医療者・園）が
// UI で明示されることを確認する。健康・安全に誤った安心を与えないための安全UX。
test('ask 回答に責任境界・免責の注意書きが表示される', async ({ page }) => {
  await installApiMocks(page)

  const DISCLAIMER =
    'このサービスは、園からのお便り等の情報の発見・想起を支援するものです。' +
    '健康・アレルギー・安全に関する最終的な判断は保護者ご自身が、専門的な判断は医療者・園にご確認ください。'

  // ストリーミングは中断させて JSON /ask へフォールバックさせる（決定的にするため）。
  await page.route('**/api/info/ask-stream', route => route.abort())
  // JSON /ask は免責付きの回答を返す。
  await page.route('**/api/info/ask', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        answer: '遠足の持ち物はお弁当と水筒です。確認が必要な可能性があります（要確認）。',
        sources: [],
        disclaimer: DISCLAIMER,
      }),
    }),
  )

  await login(page)
  await page.goto('/info?tab=ask')

  await page.locator('textarea, input[type="text"]').first().fill('遠足の持ち物は？')
  await page.getByRole('button', { name: '送信' }).click()

  // 免責の注意書き（責任境界）が表示される。
  await expect(page.getByText('ご確認のお願い:')).toBeVisible()
  await expect(page.getByText('最終的な判断は保護者', { exact: false })).toBeVisible()
})
