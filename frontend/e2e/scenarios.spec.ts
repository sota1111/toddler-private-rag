import { test, expect } from '@playwright/test'
import { installApiMocks, login } from './support/mockApi'

// シナリオ e2e (SOT-1265 / 親 SOT-1258): ユーザー操作 → 画面遷移 / 表示を検証する。
// 1テスト = 1ユーザーストーリー。すべての `/api/**` はモックして決定的にする。

test.describe('toddler-private-rag シナリオ', () => {
  test('S1: 未認証で保護ページ(/data/:id 詳細)にアクセスすると /login へリダイレクトされる (SOT-1312)', async ({ page }) => {
    await installApiMocks(page, { authed: false })
    // SOT-1312: データ一覧 /data は廃止。詳細 /data/:id は引き続き保護ページ。
    await page.goto('/data/1')
    await expect(page).toHaveURL(/\/login/)
    // ログイン画面は方式選択（メール/Google）を表示する。
    await expect(page.getByRole('button', { name: 'メールアドレスでログイン' })).toBeVisible()
  })

  test('S2: ログイン後、主要メニューを辿って各画面へ遷移できる（データメニューは廃止） (SOT-1312)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // SOT-1312: 「データ」メニューはナビゲーションから削除されている
    await expect(page.locator('nav a[href="/data"]')).toHaveCount(0)

    await page.locator('nav a[href="/info"]').first().click()
    await expect(page).toHaveURL(/\/info/)

    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await expect(page.locator('input[type="file"]')).toBeAttached()

    await page.locator('nav a[href="/"]').first().click()
    await expect(page).toHaveURL(/\/$/)
  })

  test('S3: 写真ありレコードの詳細は写真と文字起こしのみ表示しタイトルは出さない (SOT-1331)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // SOT-1331: 写真一覧から開く写真ありレコードは、写真＋文字起こしのみを表示する。
    await page.goto('/data/1')
    await expect(page).toHaveURL(/\/data\/1$/)
    await expect(page.locator('img').first()).toBeVisible()
    await expect(page.getByRole('heading', { name: '文字起こし' })).toBeVisible()
    // タイトル等（写真の上の文字）は表示しない。
    await expect(page.getByRole('heading', { name: '4月の給食メニュー' })).toHaveCount(0)
  })

  test('S5: 詳細ページで削除すると元の画面へ戻り対象が消える (SOT-1312)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // SOT-1312: 一覧は廃止。タスク一覧メニュー経由で詳細へ遷移する。
    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)
    await page.getByRole('link', { name: /運動会のお知らせ/ }).click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()

    // SOT-1401: window.confirm は廃止。アプリ内の OK/キャンセル確認モーダルで OK を押す。
    await page.getByRole('button', { name: '削除' }).click()
    await page.getByRole('button', { name: 'OK' }).click()
    // 削除後は遷移元（タスク一覧）へ戻り、対象が消える
    await expect(page).toHaveURL(/\/tasks/)
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)
  })

  test('S6: 写真を選んで自動登録すると本登録を介さず写真一覧(registered)に反映される', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)

    // 1x1 PNG を file input へ投入してOCR→自動登録フローを起動する
    await page.locator('input[type="file"]').setInputFiles({
      name: 'photo.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
        'base64',
      ),
    })

    // SOT-1288: 選択直後は確認画面が表示され、まだアップロードされない
    await expect(page.getByText('この写真でよろしいですか？')).toBeVisible()
    await page.getByRole('button', { name: 'この写真で登録' }).click()

    // SOT-1324: 本登録を介さず直接登録された完了カードと、抽出されたタイトルが表示される
    await expect(page.getByText('アップ完了（登録しました）')).toBeVisible()
    await expect(page.getByText('お知らせ_自動登録テスト', { exact: false })).toBeVisible()

    // 「写真一覧を開く」で /registered へ遷移し、本登録された写真がタイトルで並ぶ
    await page.getByRole('button', { name: '写真一覧を開く' }).click()
    await expect(page).toHaveURL(/\/registered/)
    await expect(page.getByText('お知らせ_自動登録テスト', { exact: false })).toBeVisible()
  })

  test('S7: 仮登録を本登録すると一覧から消える', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // 認証は in-memory のため、登録メニュー経由で仮登録一覧へクライアント遷移する
    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await page.locator('a[href="/drafts"]').first().click()
    await expect(page).toHaveURL(/\/drafts/)
    await expect(page.getByRole('heading', { name: '遠足のしおり（仮）' })).toBeVisible()

    await page.getByRole('button', { name: '本登録する', exact: true }).click()

    // 本登録後は仮登録一覧から消え、空表示になる
    await expect(page.getByRole('heading', { name: '遠足のしおり（仮）' })).toHaveCount(0)
    await expect(
      page.getByText('仮登録はありません。自動登録から写真をアップすると、ここに表示されます。'),
    ).toBeVisible()
  })

  test('S8: 予定画面でカレンダーと日付つき予定一覧が表示され、項目から詳細へ遷移できる (SOT-1306)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/schedule"]').first().click()
    await expect(page).toHaveURL(/\/schedule/)

    // 予定一覧見出しが表示される（カレンダー見出し「予定カレンダー」は SOT-1326 で削除）
    await expect(page.getByText('予定一覧')).toBeVisible()

    // SOT-1501: 一覧は「表示中の月」の予定のみを出す。モックの予定(2026-10-15)を表示するため、
    // 現在月から 2026年10月まで決定的にカレンダーを移動する。
    const now = new Date()
    const monthsToTarget =
      (2026 - now.getFullYear()) * 12 + (9 /* Oct=0-indexed */ - now.getMonth())
    const navButton = page.getByRole('button', {
      name: monthsToTarget >= 0 ? '次の月' : '前の月',
    })
    for (let i = 0; i < Math.abs(monthsToTarget); i += 1) {
      await navButton.click()
    }

    // 日付つき予定（運動会のお知らせ / 2026-10-15）が一覧に表示される
    const eventLink = page.getByRole('link', { name: /運動会のお知らせ/ })
    await expect(eventLink).toBeVisible()
    await expect(page.getByText('2026-10-15')).toBeVisible()

    // 項目クリックで該当データ詳細へ遷移する
    await eventLink.click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()
  })

  test('S9: タスク一覧メニューでカレンダー下と同じ一覧が表示され、項目から詳細へ遷移できる (SOT-1313)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)

    // やることリストのリスト見出しが表示される（ページ見出し h1 は SOT-1363 で削除）
    await expect(page.getByText('やることリスト')).toBeVisible()

    // 日付つき予定（運動会のお知らせ / 2026-10-15）が一覧に表示される
    const eventLink = page.getByRole('link', { name: /運動会のお知らせ/ })
    await expect(eventLink).toBeVisible()
    await expect(page.getByText('2026-10-15')).toBeVisible()

    // SOT-1502: やることリストは月ごとの見出しでグループ表示される（2026-10-15 → 2026年10月）
    await expect(page.getByRole('heading', { name: '2026年10月' })).toBeVisible()

    // SOT-1355: ステータス絞り込み。対応済では未対応の予定が消え、未対応で再表示される。
    await page.getByRole('button', { name: '対応済', exact: true }).click()
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)
    await page.getByRole('button', { name: '未対応', exact: true }).click()
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toBeVisible()

    // 項目クリックで該当データ詳細へ遷移する
    await eventLink.click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()
    // SOT-1313 reopen: 詳細でタスクの内容（本文）が確認できる
    await expect(
      page.getByText('10月15日に運動会を開催します。お弁当の準備をお願いします。'),
    ).toBeVisible()
  })

  test('S10: 設定メニューで言語・標準時間を設定でき、再読込後も保持される (SOT-1315)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/settings"]').first().click()
    await expect(page).toHaveURL(/\/settings/)
    await expect(page.getByRole('heading', { name: '設定' })).toBeVisible()

    // 言語・標準時間のコントロールが表示される
    await expect(page.getByLabel('言語')).toBeVisible()
    await expect(page.getByLabel('標準時間（タイムゾーン）')).toBeVisible()

    // 標準時間を設定する
    await page.getByLabel('標準時間（タイムゾーン）').selectOption('America/New_York')

    // 再読込しても設定が保持される（localStorage 永続化）
    await page.reload()
    await expect(page.getByLabel('標準時間（タイムゾーン）')).toHaveValue('America/New_York')
  })

  test('S11: 登録一覧メニュー（仮登録の右）から本登録タイトル一覧を開き、タイトルクリックで詳細(写真+文字起こし)へ遷移できる (SOT-1311)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // 登録メニューは登録ページ上で表示されるため、まず自動登録へ遷移してから「登録一覧」を開く
    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await page.locator('a[href="/registered"]').first().click()
    await expect(page).toHaveURL(/\/registered/)
    await expect(page.getByRole('heading', { name: '写真一覧' })).toBeVisible()

    // 本登録データのタイトルがリンクとして並ぶ（写真ありのレコードのみ）
    await expect(page.getByRole('link', { name: /4月の給食メニュー/ })).toBeVisible()

    // SOT-1318: タスク(予定日つき・写真なし)の「運動会のお知らせ」は登録一覧には出ない。
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)

    // SOT-1331: タイトルをクリックすると詳細で写真と文字起こしのみ表示される（タイトルは出さない）
    await page.getByRole('link', { name: /4月の給食メニュー/ }).click()
    await expect(page).toHaveURL(/\/data\/1/)
    await expect(page.locator('img').first()).toBeVisible()
    await expect(page.getByRole('heading', { name: '4月の給食メニュー' })).toHaveCount(0)

    // SOT-1325: 写真の下に文字起こし(OCR原文)が設定言語で表示される
    await expect(page.getByRole('heading', { name: '文字起こし' })).toBeVisible()
    await expect(page.getByText('今月の給食は和食中心です。', { exact: true })).toBeVisible()
  })

  test('S12: 仮登録画面で「全て本登録する」を押すと全 draft が本登録され一覧から消える (SOT-1341)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await page.locator('a[href="/drafts"]').first().click()
    await expect(page).toHaveURL(/\/drafts/)
    await expect(page.getByRole('heading', { name: '遠足のしおり（仮）' })).toBeVisible()

    // SOT-1401: window.confirm は廃止。アプリ内の OK/キャンセル確認モーダルで OK を押す。
    await page.getByRole('button', { name: '全て本登録する', exact: true }).click()
    await page.getByRole('button', { name: 'OK' }).click()

    // 全件本登録後は仮登録一覧から消え、空表示になる
    await expect(page.getByRole('heading', { name: '遠足のしおり（仮）' })).toHaveCount(0)
    await expect(
      page.getByText('仮登録はありません。自動登録から写真をアップすると、ここに表示されます。'),
    ).toBeVisible()
  })

  test('S13: 自動登録で複数枚の写真を同時に選んでまとめて登録できる (SOT-1498)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)

    // 2枚の 1x1 PNG を file input へまとめて投入する
    const png = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
      'base64',
    )
    await page.locator('input[type="file"]').setInputFiles([
      { name: 'photo1.png', mimeType: 'image/png', buffer: png },
      { name: 'photo2.png', mimeType: 'image/png', buffer: png },
    ])

    // 複数枚選択時は確認見出しが枚数入りになり、まとめて登録できる
    await expect(page.getByText('この2枚の写真でよろしいですか？')).toBeVisible()
    await page.getByRole('button', { name: 'この2枚を登録' }).click()

    // 完了カードで登録枚数が表示される（個別本文は仮登録一覧で確認）
    await expect(page.getByText('アップ完了（登録しました）')).toBeVisible()
    await expect(page.getByText('2枚の写真を登録しました', { exact: false })).toBeVisible()
  })

  test('S14: 仮登録画面で追加自動登録した読み取り中の写真が「読み取り中」カードとして既存の仮登録と並んで表示される (SOT-1499)', async ({ page }) => {
    // 既存の仮登録(draft)に加え、読み取り中(processing)の項目が1件ある状態を用意する。
    const NOW = new Date().toISOString()
    await installApiMocks(page, {
      authed: true,
      records: [
        {
          id: 3,
          title: '遠足のしおり（仮）',
          info_type: '資料',
          content: '遠足は来週月曜です。持ち物を確認してください。',
          status: '未対応',
          priority: '普通',
          registration_state: 'draft',
          created_at: NOW,
          updated_at: NOW,
        },
        {
          id: 4,
          title: '',
          info_type: '資料',
          content: '',
          status: '未確認',
          priority: '普通',
          registration_state: 'processing',
          created_at: NOW,
          updated_at: NOW,
          attachments: [
            {
              id: 94,
              info_id: 4,
              original_filename: 'reading.png',
              mime_type: 'image/png',
              file_size: 1024,
              created_at: NOW,
            },
          ],
        },
      ],
    })
    await login(page)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)
    await page.locator('a[href="/drafts"]').first().click()
    await expect(page).toHaveURL(/\/drafts/)

    // 既存の仮登録タスクは従来どおり表示される
    await expect(page.getByRole('heading', { name: '遠足のしおり（仮）' })).toBeVisible()
    // 読み取り中の追加登録は「読み取り中」カードとして表示される（読み取り中表示だけにならない）
    await expect(page.getByText('読み取り中', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: '写真を読み取り中' })).toBeVisible()
  })

  test('S15: 詳細でアーカイブするとやることリストから消え、設定→アーカイブ一覧に表示される (SOT-1500)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    // やることリストから対象タスクの詳細を開く
    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)
    await page.getByRole('link', { name: /運動会のお知らせ/ }).click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('heading', { name: '運動会のお知らせ' })).toBeVisible()

    // 「アーカイブ」ボタン（編集ボタンの下）で確認モーダルの OK を押す
    await page.getByRole('button', { name: 'アーカイブ', exact: true }).click()
    await page.getByRole('button', { name: 'OK' }).click()

    // アーカイブ後はやることリストへ戻り、対象が一覧から消える
    await expect(page).toHaveURL(/\/tasks/)
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)

    // 設定画面の「アーカイブを確認」ボタンからアーカイブ一覧へ遷移し、対象が表示される
    await page.locator('nav a[href="/settings"]').first().click()
    await expect(page).toHaveURL(/\/settings/)
    await page.getByRole('link', { name: /アーカイブを確認/ }).click()
    await expect(page).toHaveURL(/\/archive/)
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toBeVisible()

    // SOT-1500 再オープン#2: アーカイブ項目を開くとボタンが「アーカイブから戻す」になり、
    // 押すとアーカイブ一覧から消えてやることリストに復帰する。
    await page.getByRole('link', { name: /運動会のお知らせ/ }).click()
    await expect(page).toHaveURL(/\/data\/2$/)
    await expect(page.getByRole('button', { name: 'アーカイブ', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'アーカイブから戻す', exact: true }).click()
    await page.getByRole('button', { name: 'OK' }).click()

    // アーカイブ一覧へ戻り、対象が一覧から消える
    await expect(page).toHaveURL(/\/archive/)
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toHaveCount(0)

    // やることリストには対象が再び表示される
    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)
    await expect(page.getByRole('link', { name: /運動会のお知らせ/ })).toBeVisible()
  })

  test('S16: やることリストの月見出しの逆三角ボタンでその月の項目を表示/非表示に切り替えられる (SOT-1505)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)

    // 月見出し（2026年10月）とその月の項目が表示されている
    await expect(page.getByRole('heading', { name: '2026年10月' })).toBeVisible()
    const eventLink = page.getByRole('link', { name: /運動会のお知らせ/ })
    await expect(eventLink).toBeVisible()

    // 逆三角ボタン（見出しと同じ高さ）で折りたたむと、その月の項目が非表示になる
    const collapseBtn = page.getByRole('button', { name: '2026年10月を折りたたむ' })
    await expect(collapseBtn).toBeVisible()
    await collapseBtn.click()
    await expect(eventLink).toHaveCount(0)
    // 見出しは残り、ラベルは「展開する」に切り替わる
    await expect(page.getByRole('heading', { name: '2026年10月' })).toBeVisible()

    // 再度押すと展開され、項目が再表示される
    await page.getByRole('button', { name: '2026年10月を展開する' }).click()
    await expect(eventLink).toBeVisible()
  })

  test('S17: やることリストは凡例（絞り込み）を固定表示し、本体をスクロールできる (SOT-1506)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/tasks"]').first().click()
    await expect(page).toHaveURL(/\/tasks/)

    // 凡例（すべて / 未確認 / 未対応 / 対応済）が常に表示される
    await expect(page.getByRole('button', { name: 'すべて', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '未確認', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '未対応', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '対応済', exact: true })).toBeVisible()

    // 本体はスクロール可能な領域に入り、現在月起点で月グループが表示される
    await expect(page.getByRole('heading', { name: '2026年10月' })).toBeVisible()
    const scrollBox = page.locator('div.overflow-y-auto').filter({ hasText: '2026年10月' })
    await expect(scrollBox.first()).toBeVisible()
  })

  test('S18: 認証確認中は /login でログインフォームを表示せず、確認完了後に点滅なくダッシュボードへ遷移する (SOT-1508)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    // 認証確認(/auth/me)を遅延させ、Google redirect 復帰直後の「確認中」ウィンドウを再現する。
    // installApiMocks の後に登録することで、この route が優先される（Playwright は後勝ち）。
    await page.route('**/api/auth/me', async route => {
      await new Promise(resolve => setTimeout(resolve, 500))
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })

    await page.goto('/login')
    // SOT-1508: 確認中はローディング表示（aria-busy）にし、ログインフォームは描画しない。
    // 修正前はここでログインフォームが一瞬表示され、数秒後に遷移していた。
    await expect(page.locator('[aria-busy="true"]')).toBeVisible()
    await expect(page.getByRole('button', { name: 'メールアドレスでログイン' })).toHaveCount(0)

    // 確認完了後はダッシュボードへ遷移する（点滅なし）。
    await expect(page).toHaveURL(/\/$/)
    await expect(page.locator('a[href="/create/auto"]')).toBeVisible()
  })

  test('S19: 自動登録で PDF を選択でき、確認画面で PDF プレースホルダを表示して登録できる (SOT-1593)', async ({ page }) => {
    await installApiMocks(page, { authed: true })
    await login(page)

    await page.locator('nav a[href="/create/auto"]').first().click()
    await expect(page).toHaveURL(/\/create\/auto/)

    // file input の accept が PDF を許可していることを確認（SOT-1593: 以前は image/* のみで選べなかった）
    await expect(page.locator('input[type="file"]')).toHaveAttribute('accept', /application\/pdf|\.pdf/)

    // 最小の PDF を file input へ投入する
    await page.locator('input[type="file"]').setInputFiles({
      name: 'sample.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'),
    })

    // 確認画面が表示され、PDF は壊れた画像ではなくファイル名のプレースホルダで表示される
    await expect(page.getByText('この写真でよろしいですか？')).toBeVisible()
    await expect(page.getByText('sample.pdf')).toBeVisible()

    // SOT-1593: PDF の下に文字起こし(OCR原文)が表示される（登録前に中身を確認できる）
    await expect(page.getByText('文字起こし', { exact: true })).toBeVisible()
    await expect(page.getByText('お知らせ 7月の予定 プール 水着 タオル')).toBeVisible()

    // そのまま登録でき、完了カードが表示される（画像と同じ自動登録フロー）
    await page.getByRole('button', { name: 'この写真で登録' }).click()
    await expect(page.getByText('アップ完了（登録しました）')).toBeVisible()
  })

  test('S: 写真削除ダイアログの「関連タスクも削除」チェックボックスをタップでON/OFFできる (SOT-1595)', async ({ page }) => {
    // 関連タスクが1件以上あるときだけチェックボックスが出る。3件で固定する。
    await installApiMocks(page, { authed: true, linkedTaskCount: 3 })
    await login(page)

    await page.goto('/data/1')
    await page.getByRole('button', { name: '削除' }).click()

    // 確認ダイアログとチェックボックスが表示され、初期は未チェック。
    await expect(page.getByRole('dialog')).toBeVisible()
    const checkbox = page.getByRole('checkbox')
    await expect(checkbox).toBeVisible()
    await expect(checkbox).not.toBeChecked()

    // ラベル文言をタップしてチェックON（行全体がタップ領域）。
    await page.getByText(/関連タスクも削除/).click()
    await expect(checkbox).toBeChecked()

    // もう一度タップでOFFに戻る（iOS の二重発火で元に戻る不具合の回帰防止）。
    await page.getByText(/関連タスクも削除/).click()
    await expect(checkbox).not.toBeChecked()
  })
})
