import { test } from '@playwright/test'
import fs from 'node:fs'
import { installApiMocks, login, type MockRecord, type MockChild } from './support/mockApi'

// SOT-1435: 使い方画面(/howto)に載せる各主要画面のスクショを「スマホ画面サイズ」で再生成する。
// 人間の再オープン指示(3回目, 2026-07-01):
//  1. 2枚のおたより(園だより7月号 / 行事のお知らせ7月)を「別々の子どもの名前(さくら / あお)」で
//     文字起こし・タスク化した状態にする。
//  2. やることリストに「未確認・未対応・対応済」の3ステータスがそれぞれ存在するようにする。
//  3. 就労証明書を実行した結果「就労証明書(n/N)」が表示されている画面(=やることリスト /tasks)を撮る。
//  4. 就労証明書のタスクは「子ども未選択」(child_id なし)で表す。
//  5. メニュー画面より下はキャプチャ対象外 = 全スクショを viewport のみ(fullPage: false)で撮る。
// 実 OCR はモック環境で動かせないため、おたよりの内容をモックのシードデータとして表現する。
// 既存のモックハーネス(installApiMocks + login)を流用し、public/howto/*.png に保存する。

// スマホ画面サイズ(iPhone 相当の縦長)でキャプチャする。isMobile は Chromium プロジェクトで有効。
test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true })

const OUT = 'public/howto'
const NOW = '2026-07-01T00:00:00Z'

// サンプルの子ども2名(架空の名前)。設定画面の「お子さまの登録」に表示し、
// やることリストの行に子ども名チップとして出す。おたより2枚を別々の子どもに割り当てる。
const HOWTO_CHILDREN: MockChild[] = [
  { id: 1, name: 'さくら', created_at: NOW },
  { id: 2, name: 'あお', created_at: NOW },
]

// 2枚のおたより + 就労証明書 を文字起こし・タスク化した想定のレコード。
// tasksOnly / 掲示板は「添付なし」の行のみ表示するため attachments は付けない。
// 3ステータス網羅: 未確認 = id1,4,7,9,12 / 未対応 = id2,6,8,10,11,13 / 対応済 = id3,5。
// 就労証明書(10-13)は child_id を付けない = 「子ども未選択」で実行した結果を表す。
const HOWTO_RECORDS: MockRecord[] = [
  // --- 園だより7月号 → さくら(child_id '1') ---
  {
    id: 1, title: '七夕会', info_type: '行事', event_date: '2026-07-07',
    content: '短冊に書くお願いごとを、お子さまと一緒に考えてきてください。',
    status: '未確認', priority: '普通', child_id: '1',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 2, title: '水あそび開始', info_type: '持ち物', event_date: '2026-07-12',
    content: '水あそびが始まります。持ち物の準備をお願いします。',
    items: '水着, タオル, 着替え一式', status: '未対応', priority: '高', child_id: '1',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 3, title: '避難訓練', info_type: '行事', event_date: '2026-07-18',
    content: '火災を想定した避難訓練を行います。特別な準備はありません。',
    status: '対応済', priority: '普通', child_id: '1',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 4, title: 'お誕生日会', info_type: '行事', event_date: '2026-07-24',
    content: '7月生まれのお友だちをお祝いします。',
    status: '未確認', priority: '普通', child_id: '1',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  // --- 行事のお知らせ7月 → あお(child_id '2') ---
  {
    id: 5, title: '七夕会', info_type: '行事', event_date: '2026-07-07',
    content: '七夕の由来を知り、みんなで願いごとを書いたり歌をうたったりします。',
    status: '対応済', priority: '普通', child_id: '2',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 6, title: '水あそび開始', info_type: '持ち物', event_date: '2026-07-12',
    content: '水着・ラッシュガード・タオル・着替え一式・ビニール袋・水あそびカードをお持ちください。',
    items: '水着, ラッシュガード, タオル, 着替え一式, ビニール袋, 水あそびカード',
    status: '未対応', priority: '高', child_id: '2',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 7, title: 'お誕生日会', info_type: '行事', event_date: '2026-07-17',
    content: '主役のお子さまは、おしゃれ着での登園をお待ちしています。',
    status: '未確認', priority: '普通', child_id: '2',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 8, title: '避難訓練', info_type: '行事', event_date: '2026-07-23',
    content: '特別な準備はありません。毎月の訓練の積み重ねを大切にしています。',
    status: '未対応', priority: '普通', child_id: '2',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 9, title: 'なつまつりごっこ', info_type: '行事', event_date: '2026-07-26',
    content: '甚平やゆかたなど涼しい服装での登園をおすすめします。',
    status: '未確認', priority: '普通', child_id: '2',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  // --- 就労証明書(子ども未選択: child_id なし) 提出締切 7/31 ---
  {
    id: 10, title: '就労証明書(1/4) テンプレート入手', info_type: '提出物',
    event_date: '2026-07-09', due_date: '2026-07-09',
    content: '手順 1/4。市町村の様式(テンプレート)を入手します。最終提出期限: 2026-07-31。',
    status: '未対応', priority: '高',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 11, title: '就労証明書(2/4) 証明書発行（勤務先へ依頼）', info_type: '提出物',
    event_date: '2026-07-12', due_date: '2026-07-12',
    content: '手順 2/4。勤務先に就労証明書の発行を依頼します。最終提出期限: 2026-07-31。',
    status: '未対応', priority: '高',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 12, title: '就労証明書(3/4) 誤り確認', info_type: '提出物',
    event_date: '2026-07-26', due_date: '2026-07-26',
    content: '手順 3/4。記入内容に誤りがないか確認します。最終提出期限: 2026-07-31。',
    status: '未確認', priority: '普通',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
  {
    id: 13, title: '就労証明書(4/4) 市町村に提出', info_type: '提出物',
    event_date: '2026-07-27', due_date: '2026-07-27',
    content: '手順 4/4。市町村に就労証明書を提出します。最終提出期限: 2026-07-31。',
    status: '未対応', priority: '高',
    registration_state: 'registered', created_at: NOW, updated_at: NOW,
  },
]

// 掲示板(board)のセクション振り分け。capture 用に決定的に上書きする。
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
  await boardRoute('**/api/info/weekly', byId(1, 6)) // 七夕会(さくら)7/7, 水あそび(あお)7/12
  await boardRoute('**/api/info/next-week', byId(7, 9, 13)) // お誕生日会(あお), なつまつり(あお), 就労証明書(4/4)締切

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
    // メニュー画面より下は対象外にするため、fullPage ではなく viewport のみを撮る。
    await page.screenshot({ path: `${OUT}/${file}`, fullPage: false })
  }
})
