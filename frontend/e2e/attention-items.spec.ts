import { test, expect } from '@playwright/test'
import { installApiMocks, login, type MockAttentionItem } from './support/mockApi'

// SOT-2734: おたより登録時に生成される「⚠ 要確認（この子向け）」の併記・根拠(なぜ)ビュー・
// 確認済/非該当分類の一連を検証する。すべて `/api/**` をモックして決定的にする。

const NOW = '2026-06-01T00:00:00Z'

// SOT-2746: 「直近1週間」は項目が指す献立/おたよりの日付基準。実クロックに対して相対で日付を作る。
const ymd = (d: Date): string => d.toISOString().slice(0, 10)
const daysAgoYmd = (days: number): string => ymd(new Date(Date.now() - days * 24 * 60 * 60 * 1000))
const isoDaysAgo = (days: number): string =>
  new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()
// SOT-2746: バックエンド(SQLite 経路)が返すタイムゾーン指定の無い ISO 文字列を再現する
// （`Z` / オフセットを持たない）。フロントは tz-naive を UTC とみなして境界を正確化する。
const naiveUtcDaysAgo = (days: number): string =>
  new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().replace(/Z$/, '')

// 献立(menu_json)由来の要確認。参照日は locator.date（＝献立日）。生成時刻は別に指定できる。
function eggMenuAttention(
  menuDate: string = daysAgoYmd(1),
  createdAt: string = isoDaysAgo(1),
): MockAttentionItem {
  return {
    id: 501,
    child_id: '7',
    source_info_id: '1',
    kind: 'allergen',
    status: 'attention',
    canonical: 'egg',
    confidence: 'high',
    message: `献立（${menuDate}）の「鶏卵」がアレルゲン『たまご』（egg）に該当する可能性があります。要確認。`,
    evidence: {
      source: 'menu_json',
      span: `（${menuDate}）鶏卵`,
      profile_item: 'たまご',
      confidence: 'high',
      locator: { date: menuDate, item: '鶏卵' },
    },
    profile_item: { raw: 'たまご', canonical: 'egg' },
    llm_notes: null,
    review_status: 'unreviewed',
    reviewed_at: null,
    created_at: createdAt,
  }
}

// おたより本文(notice_text)由来の要確認。参照日が文面にも locator にも無いため created_at にフォールバックする。
function eggNoticeAttention(createdAt: string): MockAttentionItem {
  return {
    id: 502,
    child_id: '7',
    source_info_id: '1',
    kind: 'allergen',
    status: 'attention',
    canonical: 'egg',
    confidence: 'medium',
    message: 'おたより本文にアレルゲン『たまご』（egg）に関する記載があります。要確認。',
    evidence: {
      source: 'notice_text',
      span: 'たまごを含みます',
      profile_item: 'たまご',
      confidence: 'medium',
    },
    profile_item: { raw: 'たまご', canonical: 'egg' },
    llm_notes: null,
    review_status: 'unreviewed',
    reviewed_at: null,
    created_at: createdAt,
  }
}

test.describe('要確認（Attention Item） SOT-2734', () => {
  test('ダッシュボードに要確認レーンが併記され、根拠(なぜ)を確認でき、確認済を押すと消える', async ({ page }) => {
    const menuDate = daysAgoYmd(1)
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
      attentionItems: [eggMenuAttention(menuDate)],
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
    await expect(panel.getByText(`（${menuDate}）鶏卵`)).toBeVisible()
    await expect(panel.getByText('対応する配慮:')).toBeVisible()
    await expect(panel.getByText('出典:')).toBeVisible()

    // SOT-2746: 確認済を押すと、その項目は掲示板から消える（未確認のみ表示）。
    await panel.getByRole('button', { name: '確認済' }).click()
    await expect(page.getByTestId('attention-items-panel')).toHaveCount(0)
  })

  test('要確認が無いときはレーンを表示しない', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)
    await expect(page.getByTestId('attention-items-panel')).toHaveCount(0)
  })

  test('SOT-2746: 非該当（誤検出）を押しても掲示板から消える', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
      attentionItems: [eggMenuAttention()],
    })
    await login(page)
    const panel = page.getByTestId('attention-items-panel')
    await expect(panel).toBeVisible()
    await panel.getByRole('button', { name: '非該当' }).click()
    await expect(page.getByTestId('attention-items-panel')).toHaveCount(0)
  })

  test('SOT-2746: 献立日が1週間より前の要確認は、生成が最近でも表示しない', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
      // 生成(created_at)は1日前でも、参照する献立日が8日前なら直近1週間フィルタで除外される。
      attentionItems: [eggMenuAttention(daysAgoYmd(8), isoDaysAgo(1))],
    })
    await login(page)
    await expect(page.getByTestId('attention-items-panel')).toHaveCount(0)
  })

  test('SOT-2746: 参照日を持たないおたより由来は created_at(tz なし)を UTC 解釈で判定し境界内なら表示する', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
      // locator も文面日付も無いので created_at にフォールバック。tz なし6日前を UTC とみなせば境界内。
      attentionItems: [eggNoticeAttention(naiveUtcDaysAgo(6))],
    })
    await login(page)
    await expect(page.getByTestId('attention-items-panel')).toBeVisible()
    await expect(page.getByTestId('attention-recent-window')).toHaveText('直近1週間のみ表示')
  })
})
