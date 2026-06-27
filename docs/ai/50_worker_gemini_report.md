# Worker Report — SOT-1297 今日の日付（JST取得 + 掲示板/質問で利用）

## Fallback Disclosure (audit sink)
- 非応答ワーカー: Gemini CLI（実装）/ Codex CLI（検証）
- 検出した失敗モード:
  - Gemini: `IneligibleTierError`（free-tier 廃止、UNSUPPORTED_CLIENT）で `run_gemini.sh` exit 75
  - Codex: usage-limit cooldown で `run_codex.sh` 即時 exit 75（until epoch 1782609660 / 約22h先）
- 対応: Worker Non-Response Fallback Policy に基づき、Claude Code が実装・検証を直接実施。
  品質ゲートは通常どおり全項目適用。

## Summary
アプリの「今日の日付」を JST(Asia/Tokyo) で一貫取得する共通ヘルパ `app/clock.py` を新設し、
掲示板（今日/明日/今週/来週/リマインド）の日付算出を全てこのヘルパ経由に統一した。
本番 Cloud Run はコンテナ時刻が UTC のため、従来の素の `datetime.date.today()` では
JST 00:00〜09:00 の間に日付が1日ズレるリスクがあった（深夜の掲示板表示ズレ）。
加えて、質問（RAG/Ask）の LLM プロンプトに「今日の日付（曜日付き）」を1行注入し、
「今日/明日/今週/来週」などの相対的な日付の質問に答えられるようにした。

## Changed Files
- `backend/app/clock.py` — 新規。`today()` / `now_jst()` を提供（既定 Asia/Tokyo、env `APP_TIMEZONE`
  で上書き可。zoneinfo 不在時は +09:00 固定にフォールバック）。
- `backend/app/repository.py` — `from . import ... clock` 追加。SQLite/Firestore 両実装の
  `list_today` / `list_tomorrow` / `list_weekly` / `list_next_week`（計8関数）の
  `datetime.date.today()` を `clock.today()` に置換。
- `backend/app/routers/info.py` — reminders / reminders-digest の `today` と `generated_at` を
  `clock.today()` / `clock.now_jst()` に置換。未使用になった `import datetime` を除去。
- `backend/app/routers/attachments.py` — フォールバックタイトルの `today_iso` を `clock.today()` に。
  未使用 `import datetime` を除去。
- `backend/app/tagging.py` / `backend/app/extraction.py` — 日付パースの補完年 `date.today().year` を
  `clock.today().year` に（年の一貫性）。
- `backend/app/rag/providers.py` — `GeminiLLMProvider.generate` のプロンプト先頭に
  「今日の日付は YYYY-MM-DD（X曜日）です。…」を注入。`service.answer` / `generate` のシグネチャは不変。
- `backend/tests/test_dashboard_views.py` — 期待値の「今日」を `clock.today()` に統一（UTC深夜境界で
  アプリの JST 判定と一致させる）。未使用 `import datetime` を除去。
- `backend/tests/test_clock.py` — 新規。JST オフセット / `today()==now_jst().date()` /
  UTC深夜境界(UTC 6/26 23:30 == JST 6/27 08:30)で JST 日付を返すことを検証。

## Commands Run
- `python -m ruff check app tests/test_clock.py tests/test_dashboard_views.py` → All checks passed
- `python -m pytest -q` → 123 passed（従来120 + clock 3）
- frontend `npm run lint` → exit 0
- frontend `npm run build` → exit 0
- frontend `npm run e2e` → 11 passed

## Acceptance Criteria
- [x] 今日の日付を JST(Asia/Tokyo) で取得するヘルパ `clock.today()` を導入
- [x] 掲示板 today/tomorrow/weekly/next-week（SQLite/Firestore 両実装）が `clock.today()` を使用
- [x] 質問(Ask/RAG)のプロンプトに今日の日付（曜日付き）を注入
- [x] 既存テストが緑（+ clock テスト追加）

## Risks
- DB 保存用の UTC タイムスタンプ（retention / embedding_cache / repository の `now(utc)`）は意図的に
  未変更。掲示板の「今日」判定のみ JST 化した。
- 本番反映には Cloud Run への再デプロイが必要（マージ後の自動デプロイ）。`APP_TIMEZONE` 未設定でも
  既定 Asia/Tokyo で動作する。

## Next Action
READY_FOR_REVIEW
