import { expect, type Page, type Route } from '@playwright/test'

// シナリオ e2e 用の共通 API モック (SOT-1265 / 親 SOT-1258)。
// バックエンドは起動せず、すべての `/api/**` をブラウザ層で横取りして決定的に応答する（SOT-1154 を踏襲）。
// 1件のインメモリ・ストアを保持し、作成/更新/削除/本登録(finalize) が一覧・詳細・仮登録に反映される。

export interface MockRecord {
  id: number
  title: string
  info_type: string
  content: string
  date?: string
  event_date?: string
  due_date?: string
  items?: string
  status: string
  priority: string
  tags?: string
  memo?: string
  child_id?: string
  registration_state?: string
  is_archived?: boolean
  created_at: string
  updated_at: string
  attachments?: Array<{
    id: number
    info_id: number
    original_filename: string
    mime_type: string
    file_size: number
    created_at: string
    ocr_text?: string
  }>
}

// 1x1 PNG。添付ファイル取得 (`/api/attachments/{id}/file`) の応答に使う。
const PNG_1x1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
)

const NOW = '2026-06-01T00:00:00Z'

// 既定シード: 本登録済み2件 + 仮登録(draft)1件。
export function defaultRecords(): MockRecord[] {
  return [
    {
      id: 1,
      title: '4月の給食メニュー',
      info_type: '給食',
      content: '今月の給食は和食中心です。アレルギーのある方は事前にご連絡ください。',
      status: '対応済',
      priority: '普通',
      items: 'おはし',
      memo: '毎月更新',
      registration_state: 'registered',
      created_at: NOW,
      updated_at: NOW,
      attachments: [
        {
          id: 92,
          info_id: 1,
          original_filename: 'menu.png',
          mime_type: 'image/png',
          file_size: 1024,
          created_at: NOW,
          ocr_text: '今月の給食は和食中心です。',
        },
      ],
    },
    {
      id: 2,
      title: '運動会のお知らせ',
      info_type: 'お知らせ',
      content: '10月15日に運動会を開催します。お弁当の準備をお願いします。',
      event_date: '2026-10-15',
      status: '未対応',
      priority: '高',
      registration_state: 'registered',
      created_at: NOW,
      updated_at: NOW,
    },
    {
      id: 3,
      title: '遠足のしおり（仮）',
      info_type: '資料',
      content: '遠足は来週月曜です。持ち物を確認してください。',
      items: '水筒, おやつ',
      status: '未対応',
      priority: '普通',
      registration_state: 'draft',
      created_at: NOW,
      updated_at: NOW,
      attachments: [
        {
          id: 91,
          info_id: 3,
          original_filename: 'shiori.png',
          mime_type: 'image/png',
          file_size: 1024,
          created_at: NOW,
        },
      ],
    },
  ]
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

// SOT-1435: 使い方スクショ用に、子ども（お子さまの登録）をシードできるようにする。
export interface MockChild {
  id: number | string
  name: string
  created_at: string
}

export interface MockApiOptions {
  authed?: boolean
  records?: MockRecord[]
  children?: MockChild[]
}

// `/api/**` をすべてモックする。戻り値のストアを使ってテスト側でアサートできる。
export async function installApiMocks(page: Page, opts: MockApiOptions = {}) {
  const authed = opts.authed ?? true
  const store: MockRecord[] = opts.records ?? defaultRecords()
  // SOT-1435: 子どもストア。既定は空配列（従来どおり「お子さま未登録」）で、既存スペックの挙動は不変。
  const childStore: MockChild[] = opts.children ?? []
  let nextId = Math.max(0, ...store.map(r => r.id)) + 1
  let nextAttId = 1000
  let nextChildId = Math.max(0, ...childStore.map(c => Number(c.id) || 0)) + 1

  await page.route('**/api/**', async route => {
    const req = route.request()
    const method = req.method()
    const path = new URL(req.url()).pathname.replace(/^\/api/, '')

    // --- 認証 ---
    if (path === '/auth/me') return json(route, authed ? 200 : 401, {})
    if (path === '/auth/session' || path === '/auth/logout') return json(route, 200, {})

    // --- 子ども（お子さまの登録, SOT-1368 / SOT-1435） ---
    if (path === '/children' || path === '/children/') {
      if (method === 'GET') return json(route, 200, childStore)
      if (method === 'POST') {
        const data = JSON.parse(req.postData() || '{}')
        const child: MockChild = {
          id: nextChildId++,
          name: (data.name ?? '').trim(),
          created_at: NOW,
        }
        childStore.push(child)
        return json(route, 200, child)
      }
    }
    const childIdMatch = path.match(/^\/children\/(\w+)$/)
    if (childIdMatch && method === 'DELETE') {
      const idx = childStore.findIndex(c => String(c.id) === childIdMatch[1])
      if (idx !== -1) childStore.splice(idx, 1)
      return json(route, 200, { deleted: true })
    }

    // --- 添付 ---
    const fileMatch = path.match(/^\/attachments\/(\d+)\/file$/)
    if (fileMatch) {
      return route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1x1 })
    }
    // SOT-1325: 文字起こし(OCR原文)を設定言語で返す。モックは翻訳せず ocr_text をそのまま返す。
    const transcriptionMatch = path.match(/^\/attachments\/(\d+)\/transcription$/)
    if (transcriptionMatch) {
      const attId = Number(transcriptionMatch[1])
      const language = new URL(req.url()).searchParams.get('language') || 'ja'
      const att = store
        .flatMap(r => r.attachments ?? [])
        .find(a => a.id === attId)
      return json(route, 200, {
        text: att?.ocr_text ?? '',
        ocr_status: att?.ocr_text ? 'done' : 'pending',
        language,
      })
    }
    if (/^\/attachments\/\d+$/.test(path) && method === 'DELETE') return json(route, 200, {})

    // --- info コレクションの特殊エンドポイント（数値ID判定より先に処理する） ---
    if (path === '/info/drafts') {
      return json(route, 200, store.filter(r => r.registration_state === 'draft'))
    }
    // SOT-1499: 読み取り中(processing)の項目一覧。仮登録画面の「読み取り中」カード用。
    if (path === '/info/drafts/processing') {
      return json(route, 200, store.filter(r => r.registration_state === 'processing'))
    }
    if (path === '/info/drafts/processing-count') {
      return json(route, 200, { count: store.filter(r => r.registration_state === 'processing').length })
    }
    // SOT-1500: アーカイブ一覧。is_archived=true の本登録項目のみを返す。
    if (path === '/info/archived') {
      return json(route, 200, store.filter(r => r.registration_state !== 'draft' && r.is_archived))
    }
    if (path === '/info/reminders') return json(route, 200, { items: [] })
    if (['/info/today', '/info/tomorrow', '/info/weekly', '/info/next-week', '/info/pending'].includes(path)) {
      return json(route, 200, [])
    }
    if (path === '/info/extract' && method === 'POST') {
      // 文字起こし(OCR)で実テキストが得られた前提の決定的な抽出結果。
      return json(route, 200, {
        title: 'お知らせ_自動登録テスト',
        info_type: 'お知らせ',
        content: '7月の予定をお知らせします。プールが始まります。',
        items: '水着, タオル',
        date: '',
        raw_text: 'お知らせ 7月の予定 プール 水着 タオル',
        detected_dates: [],
        detected_items: ['水着', 'タオル'],
        categories: {
          submissions: [],
          belongings: ['水着', 'タオル'],
          deadlines: [],
          events: ['プール'],
          notes: ['名前を記入してください'],
        },
      })
    }
    if (path === '/info/ask' && method === 'POST') {
      return json(route, 200, { answer: '', sources: [] })
    }
    if (path === '/info/suggest-tags' && method === 'POST') {
      return json(route, 200, { info_type: '資料', priority: '普通', tags: [], source: 'heuristic' })
    }
    if (path === '/info/hybrid-search') return json(route, 200, { results: [], total: 0 })

    // --- info コレクション ---
    if (path === '/info/' || path === '/info') {
      if (method === 'GET') {
        // 一覧は本登録(registered)のみを返す（draft は /info/drafts 側）。
        // SOT-1500: アーカイブ済み(is_archived)はアクティブ一覧から除外する。
        return json(route, 200, store.filter(r => r.registration_state !== 'draft' && !r.is_archived))
      }
      if (method === 'POST') {
        const data = JSON.parse(req.postData() || '{}')
        const rec: MockRecord = {
          id: nextId++,
          title: data.title ?? '',
          info_type: data.info_type ?? '資料',
          content: data.content ?? '',
          date: data.date ?? '',
          event_date: data.event_date ?? '',
          due_date: data.due_date ?? '',
          items: data.items ?? '',
          status: data.status ?? '未確認',
          priority: data.priority ?? '普通',
          tags: data.tags ?? '',
          memo: data.memo ?? '',
          registration_state: data.registration_state ?? 'registered',
          created_at: NOW,
          updated_at: NOW,
          attachments: [],
        }
        store.push(rec)
        return json(route, 200, rec)
      }
    }

    // --- 個別 info: /info/{id} と /info/{id}/finalize, /info/{id}/attachments ---
    const finalizeMatch = path.match(/^\/info\/(\d+)\/finalize$/)
    if (finalizeMatch && method === 'POST') {
      const rec = store.find(r => r.id === Number(finalizeMatch[1]))
      if (!rec) return json(route, 404, {})
      rec.registration_state = 'registered'
      return json(route, 200, rec)
    }
    const attachMatch = path.match(/^\/info\/(\d+)\/attachments$/)
    if (attachMatch && method === 'POST') {
      const infoId = Number(attachMatch[1])
      const rec = store.find(r => r.id === infoId)
      const att = {
        id: nextAttId++,
        info_id: infoId,
        original_filename: 'photo.png',
        mime_type: 'image/png',
        file_size: 2048,
        created_at: NOW,
      }
      if (rec) {
        rec.attachments = [...(rec.attachments ?? []), att]
        // SOT-1293/SOT-1324: サーバ側で OCR→enrich→本登録(registered)昇格が行われるのを再現する。
        // processing のレコードは写真添付をトリガーに enrich 済みの registered へ直接昇格する
        // （本登録ステップを介さない）。
        if (rec.registration_state === 'processing') {
          rec.registration_state = 'registered'
          rec.title = rec.title || 'お知らせ_自動登録テスト'
          rec.info_type = 'お知らせ'
          rec.content = '7月の予定をお知らせします。プールが始まります。'
          rec.items = '水着, タオル'
          rec.updated_at = NOW
        }
      }
      return json(route, 200, att)
    }
    const idMatch = path.match(/^\/info\/(\d+)$/)
    if (idMatch) {
      const id = Number(idMatch[1])
      const idx = store.findIndex(r => r.id === id)
      if (method === 'GET') {
        if (idx === -1) return json(route, 404, {})
        return json(route, 200, store[idx])
      }
      if (method === 'PUT') {
        if (idx === -1) return json(route, 404, {})
        const data = JSON.parse(req.postData() || '{}')
        store[idx] = { ...store[idx], ...data, updated_at: NOW }
        return json(route, 200, store[idx])
      }
      if (method === 'DELETE') {
        if (idx !== -1) store.splice(idx, 1)
        return json(route, 200, {})
      }
    }

    // 未知のエンドポイントは空配列でフォールバック（一覧系のガードに合わせる）。
    return json(route, 200, [])
  })

  return store
}

// ログインフォームから認証してダッシュボードへ遷移する（auth/me 解決前に /login へ
// 一度バウンスするため、実フローでログインするのが最も確実）。
export async function login(page: Page) {
  await page.goto('/login')
  // 方式選択画面で「メールアドレスでログイン」を選ぶとフォームが表示される。
  await page.getByRole('button', { name: 'メールアドレスでログイン' }).click()
  await page.locator('input[type="email"]').fill('test@example.com')
  await page.locator('input[type="password"]').fill('password123')
  await page.locator('button[type="submit"]').click()
  // 認証後はボトムナビ（登録リンク）が表示される。
  await expect(page.locator('a[href="/create/auto"]')).toBeVisible()
}
