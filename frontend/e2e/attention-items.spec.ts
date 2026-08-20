import { test, expect } from '@playwright/test'
import { installApiMocks, login, type MockAttentionItem } from './support/mockApi'

// SOT-2734: おたより登録時に生成される「⚠ 要確認（この子向け）」の併記・根拠(なぜ)ビュー・
// 確認済/非該当分類の一連を検証する。すべて `/api/**` をモックして決定的にする。

const NOW = '2026-06-01T00:00:00Z'

function eggAttention(): MockAttentionItem {
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
    created_at: NOW,
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
})
