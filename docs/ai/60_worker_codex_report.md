# Worker Report

## Summary
SOT-1297「今日の日付」の初期タスク確認。**actionable**。
要件: アプリが「今日の日付」を取得し、(1) 掲示板（ダッシュボード）表示と (2) 質問（RAG/Ask）の
両方で使えるようにする。

調査の結果、現状には2つの問題がある:
1. **タイムゾーン未適用（バグリスク）**: 掲示板の日付算出は全て `datetime.date.today()`
   = サーバローカル時刻（Cloud Run は UTC）。タイムゾーン(Asia/Tokyo)未適用のため、
   JST 00:00〜09:00 の間はサーバが「前日」と判定し、今日/明日/今週/来週が1日ズレる。
2. **質問が今日の日付を認識しない**: RAG/Ask のプロンプト(`rag/providers.py`
   `GeminiLLMProvider.generate`)に today の情報が一切含まれず、「明日の予定は？」等の
   相対日付の質問に答えられない。

## Worker Non-Response Disclosure (audit)
- 非応答ワーカー: Codex CLI
- 検出した失敗モード: usage-limit cooldown により `scripts/ai/run_codex.sh` が即時 exit 75
  (CODEX_COOLDOWN_ACTIVE, until epoch 1782609660 / 約22時間先)。リトライ不要と判断。
- 対応: Worker Non-Response Fallback Policy に基づき Claude Code がこのタスク確認を直接実施。
  実装は通常どおり Gemini へ委譲する。

## Changed Files
- none (read-only task check)

## Commands Run
- grep `date.today|datetime.now|utcnow|ZoneInfo|Asia/Tokyo|timezone` over backend/app
- read repository.py (list_today/list_tomorrow/list_weekly/list_next_week, SQLite & Firestore)
- read rag/service.py, rag/providers.py (prompt 構築)

## Findings
### 掲示板（ダッシュボード）の「今日」算出箇所（すべて naive `date.today()` = UTC on Cloud Run）
- SQLite 実装 `backend/app/repository.py`:
  - `list_today` :160 / `list_tomorrow` :171 / `list_weekly` :181-182 / `list_next_week` :192-194
- Firestore 実装 `backend/app/repository.py`:
  - `list_today` :504 / `list_tomorrow` :521 / `list_weekly` :546-548 / `list_next_week` :573-575
- サマリ系エンドポイント `backend/app/routers/info.py`:
  - :249, :268 (`today = datetime.date.today()`), :253/:272 (`generated_at`)
- その他 today 依存: `tagging.py:49`, `extraction.py:364`, `attachments.py:85`(today_iso)

### 質問（Ask/RAG）パイプライン
- ルータ: `backend/app/routers/info.py:62` `POST /ask` → `service.answer(query, top_k)`
- サービス: `backend/app/rag/service.py:123` `answer()` → `llm_provider.generate(query, contexts)`
- プロンプト構築: `backend/app/rag/providers.py:124-133` `GeminiLLMProvider.generate`
  → **today の情報なし**。ここに「今日の日付」を注入する必要がある。

### タイムゾーンのバグリスク
- 中央集約された TZ ヘルパや config モジュールは存在しない（`config.py` なし）。
- 各所が独立に `datetime.date.today()` を呼ぶため、JST を1か所で定義して全置換するのが安全。

### 変更が必要な file:line（最小変更の見立て）
1. JST の今日を返すヘルパを新設（例 `backend/app/clock.py` の `today_jst()` / `now_jst()`）。
   タイムゾーンは `zoneinfo.ZoneInfo("Asia/Tokyo")`、env `APP_TIMEZONE` で上書き可。
2. 掲示板系 `date.today()` をヘルパ呼び出しに置換
   (repository.py SQLite/Firestore 8関数, info.py:249/268)。
3. `rag/providers.py` の prompt に「本日は YYYY-MM-DD (曜日) です。」を1行注入し、
   相対日付の質問に答えられるようにする。`service.answer`/`generate` のシグネチャは可能なら不変。
4. 既存テスト `test_dashboard_views.py` / `test_rag.py` は期待値を同じヘルパで算出するよう調整。

## Acceptance Criteria
- [ ] アプリが正しいタイムゾーン(JST/Asia/Tokyo)で今日の日付を取得している
- [ ] 掲示板の today/tomorrow/weekly/next-week がその日付を使う（UTC 深夜ズレ解消）
- [ ] 質問（Ask/RAG）が今日の日付を認識できる（プロンプトに today 注入）

## Risks
- TZ 置換は掲示板の挙動に直結。SQLite と Firestore 両実装を同一ヘルパで揃えること。
- テストが `date.today()` 前提だと JST 化で UTC 深夜境界に弱くなる → テストもヘルパ化。

## Next Action
READY_FOR_REVIEW
