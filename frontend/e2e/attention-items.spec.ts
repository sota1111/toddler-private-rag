import { test, expect } from '@playwright/test'
import { installApiMocks, login, type MockAttentionItem } from './support/mockApi'

// SOT-2734: おたより登録時に生成される「⚠ 要確認（この子向け）」の併記・根拠(なぜ)ビュー・
// 確認済/非該当分類の一連を検証する。すべて `/api/**` をモックして決定的にする。

const NOW = '2026-06-01T00:00:00Z'
// SOT-2746: 掲示板の「要確認」は直近1週間の項目のみ表示するため、表示させたい項目は
// 実クロック基準で最近（数日前）の created_at にする。
const isoDaysAgo = (days: number): string =>
  new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()

// SOT-2746: バックエンド(SQLite 経路)が返すタイムゾーン指定の無い ISO 文字列を再現する
// （`Z` / オフセットを持たない）。フロントは tz-naive を UTC とみなして境界を正確化する。
const naiveUtcDaysAgo = (days: number): string =>
  new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().replace(/Z$/, '')

function eggAttention(createdAt: string = isoDaysAgo(1)): MockAttentionItem {
  return {
    id: 501,
    child_id: '7',
    source_info_id: '1',
    kind: 'allergen',
    status: 'attention',
    canonical: 'egg',
    confidence: 'high',
    message: '献立（2026-09-01）の「鶏卵」がアレルゲン『たまご』（egg）に該当する可能性があります。要確認。',
    evidence: {
      source: 'menu_json',
      span: '（2026-09-01）鶏卵',
      profile_item: 'たまご',
      confidence: 'high',
      locator: { date: '2026-09-01', item: '鶏卵' },
    },
    profile_item: { raw: 'たまご', canonical: 'egg' },
    llm_notes: null,
    review_status: 'unreviewed',
    reviewed_at: null,
    created_at: createdAt,
  }
}

test.describe('要確認（Attention Item） SOT-2734', () => {
  test('ダッシュボードに要確認レーンが併記され、根拠(なぜ)を確認でき、確認済/非該当に分類できる', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
      attentionItems: [eggAttention()],
    })
    await login(page)

    // レーンが最上部に併記される。
    const panel = page.getByTestId('attention-items-panel')
    await expect(panel).toBeVisible()
    await expect(panel.getByText('要確認（この子向け）')).toBeVisible()
    // SOT-2746: 「直近1週間のみ表示」インジケータが常時見えて、フィルタが効いていると確認できる。
    await expect(panel.getByTestId('attention-recent-window')).toHaveText('直近1週間のみ表示')
    await expect(panel.getByText(/鶏卵.*たまご.*要確認/)).toBeVisible()
    // 対象の子ども名チップが併記される。
    await expect(panel.getByText('たろう')).toBeVisible()
    // 断定表現（安全/食べられる）は出さない。
    await expect(panel.getByText(/安全|食べられます/)).toHaveCount(0)

    // 根拠（なぜ）を開くと該当箇所/対応する配慮/出典が見える。
    await expect(panel.getByText('該当箇所:')).toHaveCount(0)
    await panel.getByRole('button', { name: 'なぜ' }).click()
    await expect(panel.getByText('該当箇所:')).toBeVisible()
    await expect(panel.getByText('（2026-09-01）鶏卵')).toBeVisible()
    await expect(panel.getByText('対応する配慮:')).toBeVisible()
    await expect(panel.getByText('出典:')).toBeVisible()

    // 確認済に分類でき、状態バッジが更新される。
    await panel.getByRole('button', { name: '確認済' }).click()
    await expect(panel.getByText('確認済')).toBeVisible()
    // レビュー後は確認済/非該当ボタンが消え、未確認に戻す導線が出る。
    await expect(panel.getByRole('button', { name: '未確認に戻す' })).toBeVisible()
    await expect(panel.getByRole('button', { name: '非該当' })).toHaveCount(0)
  })

  test('要確認が無いときはレーンを表示しない', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)
    await expect(page.getByTestId('attention-items-panel')).toHaveCount(0)
  })

  test('SOT-2746: 1週間より前の要確認は表示しない', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
      // 8日前に生成された項目は直近1週間フィルタで除外され、レーンごと非表示になる。
      attentionItems: [eggAttention(isoDaysAgo(8))],
    })
    await login(page)
    await expect(page.getByTestId('attention-items-panel')).toHaveCount(0)
  })

  test('SOT-2746: tz なし(SQLite 経路)の created_at も UTC 解釈で境界内なら表示する', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
      // タイムゾーン指定の無い 6 日前の文字列。UTC とみなせば直近1週間内なので表示される。
      attentionItems: [eggAttention(naiveUtcDaysAgo(6))],
    })
    await login(page)
    await expect(page.getByTestId('attention-items-panel')).toBeVisible()
    await expect(page.getByTestId('attention-recent-window')).toHaveText('直近1週間のみ表示')
  })
})
