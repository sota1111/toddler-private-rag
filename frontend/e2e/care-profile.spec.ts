import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// SOT-2732: 個別配慮プロファイルの登録→再表示→編集→削除の一連と、API エラー時のハンドリングを検証する。
// すべて `/api/**` をモックして決定的にする。

const NOW = '2026-06-01T00:00:00Z'

test.describe('個別配慮プロファイル SOT-2732', () => {
  test('子ごとに登録→再表示→編集→削除できる（最終更新日も表示）', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      // SOT-2746: 2名以上のときは自動選択されない（1名だけ自動選択の別テストで検証）。
      children: [
        { id: 7, name: 'たろう', created_at: NOW },
        { id: 8, name: 'はなこ', created_at: NOW },
      ],
    })
    await login(page)
    await page.goto('/settings')

    const panel = page.getByTestId('care-profile-panel')
    await expect(panel).toBeVisible()

    // 子を選ぶ。未選択時はフォームが出ない。
    await expect(panel.getByRole('button', { name: '保存' })).toHaveCount(0)
    await panel.getByTestId('care-profile-child-select').selectOption('7')

    // 型付き属性（アレルゲン/配慮カテゴリ）を選び、自由記述を入れて保存（=新規登録 POST）。
    await panel.getByRole('button', { name: '卵', exact: true }).click()
    await panel.getByRole('button', { name: '動物接触', exact: true }).click()
    await panel.getByLabel('自由記述').fill('卵は加熱少量なら可')
    await panel.getByRole('button', { name: '保存', exact: true }).click()

    await expect(panel.getByText('保存しました')).toBeVisible()
    // 最終更新日が保持・表示される。
    await expect(panel.getByTestId('care-profile-updated-at')).toContainText('最終更新日')

    // 再表示: 別の子（なし）→ たろう へ戻すと保存済みの状態が復元される。
    await panel.getByTestId('care-profile-child-select').selectOption('')
    await expect(panel.getByRole('button', { name: '保存' })).toHaveCount(0)
    await panel.getByTestId('care-profile-child-select').selectOption('7')

    const eggChip = panel.getByRole('button', { name: '卵', exact: true })
    await expect(eggChip).toHaveAttribute('aria-pressed', 'true')
    await expect(panel.getByLabel('自由記述')).toHaveValue('卵は加熱少量なら可')
    // 既存プロファイルがあるので削除導線が出る。
    await expect(panel.getByRole('button', { name: 'プロファイルを削除' })).toBeVisible()

    // 編集: 乳を追加して保存（=更新 PUT）。
    await panel.getByRole('button', { name: '乳', exact: true }).click()
    await panel.getByRole('button', { name: '保存', exact: true }).click()
    await expect(panel.getByText('保存しました')).toBeVisible()
    await expect(panel.getByRole('button', { name: '乳', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    // 削除: 確認→削除するとフォームが空へ戻り、削除導線が消える。
    await panel.getByRole('button', { name: 'プロファイルを削除' }).click()
    await panel.getByRole('button', { name: '削除する', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'プロファイルを削除' })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: '卵', exact: true })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    await expect(panel.getByTestId('care-profile-updated-at')).toHaveCount(0)
  })

  test('お子さまが1名なら自動選択され、登録すると一覧に反映されて行タップで編集に戻れる', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 9, name: 'そうた', created_at: NOW }],
    })
    await login(page)
    await page.goto('/settings')

    const panel = page.getByTestId('care-profile-panel')
    // 1名だけなので自動選択され、フォーム（保存ボタン）が最初から出る。
    await expect(panel.getByRole('button', { name: '保存', exact: true })).toBeVisible()

    // 未登録なので一覧は空メッセージ。
    const summary = panel.getByTestId('care-profile-summary')
    await expect(summary).toContainText('まだ登録がありません')

    // 卵を選んで保存（=新規登録）。
    await panel.getByRole('button', { name: '卵', exact: true }).click()
    await panel.getByRole('button', { name: '保存', exact: true }).click()
    await expect(panel.getByText('保存しました')).toBeVisible()

    // 一覧に「そうた」と「卵」チップが反映される。
    await expect(summary).toContainText('そうた')
    await expect(summary.getByText('卵', { exact: true })).toBeVisible()

    // 選択を外してから一覧の行をタップすると、その子の編集に戻れる（卵が押下状態）。
    await panel.getByTestId('care-profile-child-select').selectOption('')
    await expect(panel.getByRole('button', { name: '保存' })).toHaveCount(0)
    await summary.getByRole('button', { name: /そうた/ }).click()
    await expect(panel.getByRole('button', { name: '卵', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  test('保存 API がエラーのときはエラーメッセージを表示する', async ({ page }) => {
    await installApiMocks(page, {
      authed: true,
      children: [{ id: 7, name: 'たろう', created_at: NOW }],
    })
    // installApiMocks の後に登録したハンドラが優先される。POST /care-profiles だけ 500 にする。
    await page.route('**/api/care-profiles', async (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
      }
      return route.fallback()
    })
    await login(page)
    await page.goto('/settings')

    const panel = page.getByTestId('care-profile-panel')
    await panel.getByTestId('care-profile-child-select').selectOption('7')
    await panel.getByRole('button', { name: '卵', exact: true }).click()
    await panel.getByRole('button', { name: '保存', exact: true }).click()

    await expect(panel.getByText('保存に失敗しました。')).toBeVisible()
    await expect(panel.getByText('保存しました')).toHaveCount(0)
  })
})
