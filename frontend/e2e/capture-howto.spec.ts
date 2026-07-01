import { test } from '@playwright/test'
import fs from 'node:fs'
import { installApiMocks, login, type MockRecord, type MockChild } from './support/mockApi'

// SOT-1435: 使い方画面(/howto)に載せる各主要画面のスクショを「スマホ画面サイズ」で再生成する。
// 人間の再オープン指示:
//  1. 2枚のおたより(行事のお知らせ7月 / 園だより7月号)をサンプルの子ども「さくら」で
//     文字起こし・タスク化した状態にし、スマホ画面サイズで撮り直す。
//  2. 「書類の締切設定」の使い方は、就労証明書の提出締切(提出目標日 7/31)を反映して撮る。
// 実 OCR はモック環境で動かせないため、おたよりの内容をモックのシードデータとして表現する。
// 既存のモックハーネス(installApiMocks + login)を流用し、public/howto/*.png に保存する。

// スマホ画面サイズ(iPhone 相当の縦長)でキャプチャする。isMobile は Chromium プロジェクトで有効。
test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true })

const OUT = 'public/howto'
const NOW = '2026-07-01T00:00:00Z'
const CHILD_ID = '1'

// サンプルの子ども(架空の名前)。設定画面の「お子さまの登録」に1名表示させる。
const HOWTO_CHILDREN: MockChild[] = [{ id: 1, name: 'さくら', created_at: NOW }]

// 2枚のおたより + 就労証明書 を文字起こし・タスク化した想定のレコード。
// tasksOnly / 掲示板は「添付なし」の行のみ表示するため attachments は付けない。
const HOWTO_RECORDS: MockRecord[] = [
  {
    id: 1, title: '七夕会', info_type: '行事', event_date: '2026-07-07',
    content: '短冊に書くお願いごとを、お子さまと一緒に考えてきてください。',
    status: '未確認', priority: '普通', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 2, title: '水あそび開始', info_type: '持ち物', event_date: '2026-07-12',
    content: '水あそびが始まります。持ち物の準備をお願いします。',
    items: '水着, ラッシュガード, タオル, 着替え一式, ビニール袋, 水あそびカード',
    status: '未対応', priority: '高', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 3, title: 'お誕生日会', info_type: '行事', event_date: '2026-07-17',
    content: '7月生まれのお友だちをお祝いします。おしゃれ着での登園をお待ちしています。',
    status: '未確認', priority: '普通', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 4, title: '避難訓練', info_type: '行事', event_date: '2026-07-18',
    content: '火災を想定した避難訓練を行います。特別な準備はありません。',
    status: '未確認', priority: '普通', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 5, title: 'なつまつりごっこ', info_type: '行事', event_date: '2026-07-26',
    content: '甚平やゆかたなど涼しい服装での登園をおすすめします。',
    status: '未確認', priority: '普通', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 6, title: '就労証明書の提出', info_type: '提出物',
    event_date: '2026-07-31', due_date: '2026-07-31',
    content:
      '保育を必要とする状況の確認のため、就労証明書をご提出ください。提出方法: 紙(事務室)またはアプリの提出機能。',
    items: '就労証明書', status: '未対応', priority: '高', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 7, title: '毎日の持ち物・名前の記入', info_type: '持ち物',
    content:
      '水筒(お茶またはお水)を毎日持参、帽子の着用、着替えを多めにご用意ください。持ち物には必ず名前の記入をお願いします。',
    items: '水筒, 帽子, 着替え',
    status: '未対応', priority: '普通', child_id: CHILD_ID,
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
]

// 掲示板(board)のセクション振り分け。今日は 2026-07-01 想定で直近の予定を当週/翌週に置く。
const byId = (...ids: number[]) => HOWTO_RECORDS.filter(r => ids.includes(r.id))

test('capture how-to screenshots (smartphone size)', async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true })
  await installApiMocks(page, { records: HOWTO_RECORDS, children: HOWTO_CHILDREN })

  // 掲示板のセクションはサーバ集計(/info/today など)を使うため capture 用に上書きする。
  // installApiMocks の後に登録することで、これらの route が優先される(Playwright は後勝ち)。
  const boardRoute = (glob: string, items: MockRecord[]) =>
    page.route(glob, route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items) }),
    )
  await boardRoute('**/api/info/today', [])
  await boardRoute('**/api/info/tomorrow', [])
  await boardRoute('**/api/info/weekly', byId(1, 2)) // 七夕会 7/7, 水あそび 7/12
  await boardRoute('**/api/info/next-week', byId(3, 4, 6)) // お誕生日会, 避難訓練, 就労証明書(締切7/31)

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
