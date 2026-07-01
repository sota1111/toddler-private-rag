import { test } from '@playwright/test'
import fs from 'node:fs'
import { installApiMocks, login, type MockRecord, type MockChild } from './support/mockApi'

// SOT-1433: README の「実例(Before/After)」用スクショを生成する。
// 提出書類先回りエージェント(submission_agent.py)が、就労証明書のおたよりから
// 「①提出が必要な書類を抽出 → ②Google Search grounding で公式手順・発行元・所要期間を自律調査
//  → ③最終締切(7/30)から逆算して準備タスクを日付付きで自動生成」した After 状態を、
// やることリスト(/tasks)として撮影する。
//
// タスク名・締切は backend/tests/test_submission_agent.py:test_build_drafts_per_step_backward_chain
// の検証済みの値に一致させている（捏造ではなく、実際の逆算ロジックが生成する結果）:
//   最終提出期限 2026-07-30 / 手順 テンプレート入手(3日) 証明書発行(14日) 誤り確認(1日) 市町村に提出(3日)
//   → 生成される準備タスクの due_date = 2026-07-09 / 07-12 / 07-26 / 07-27
// 実 OCR / Search grounding はモック環境で動かせないため、生成結果をシードデータとして表現する。
// 既存のモックハーネス(installApiMocks + login)を流用し、public/howto/agent-demo.png に保存する。

test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true })

const OUT = 'public/howto'
const NOW = '2026-07-01T00:00:00Z'
const CHILD_ID = '1'

const DEMO_CHILDREN: MockChild[] = [{ id: 1, name: 'さくら', created_at: NOW }]

// エージェントが締切逆算で自動生成した「就労証明書」の準備タスク 4 件。
// タイトル形式は submission_agent.build_submission_task_drafts の実出力
//「書類名(何番目/全数) 手順の要約」に合わせる。
const DEMO_RECORDS: MockRecord[] = [
  {
    id: 1, title: '就労証明書(1/4) テンプレート入手', info_type: '提出物',
    event_date: '2026-07-09', due_date: '2026-07-09',
    content: '手順 1/4。市町村の様式(テンプレート)を入手します。所要期間の目安: 3日。最終提出期限: 2026-07-30。',
    status: '未対応', priority: '高', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 2, title: '就労証明書(2/4) 証明書発行（勤務先へ依頼）', info_type: '提出物',
    event_date: '2026-07-12', due_date: '2026-07-12',
    content: '手順 2/4。勤務先に就労証明書の発行を依頼します。所要期間の目安: 14日。最終提出期限: 2026-07-30。',
    status: '未対応', priority: '高', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 3, title: '就労証明書(3/4) 誤り確認', info_type: '提出物',
    event_date: '2026-07-26', due_date: '2026-07-26',
    content: '手順 3/4。記入内容に誤りがないか確認します。所要期間の目安: 1日。最終提出期限: 2026-07-30。',
    status: '未対応', priority: '普通', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 4, title: '就労証明書(4/4) 市町村に提出', info_type: '提出物',
    event_date: '2026-07-27', due_date: '2026-07-27',
    content: '手順 4/4。市町村に就労証明書を提出します。所要期間の目安: 3日。最終提出期限: 2026-07-30。',
    status: '未対応', priority: '高', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
]

test('capture agent Before/After example (submission backward-planning)', async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true })
  await installApiMocks(page, { records: DEMO_RECORDS, children: DEMO_CHILDREN })

  await login(page)

  await page.goto('/tasks')
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${OUT}/agent-demo.png`, fullPage: true })
})
