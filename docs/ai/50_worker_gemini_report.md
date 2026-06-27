# Worker Report — SOT-1315 (Claude fallback)

## Summary
SOT-1315「設定メニュー追加」。

**Fallback disclosure (audit):** BOTH workers were non-responsive.
- Gemini CLI: `scripts/ai/run_gemini.sh` exit 75 = IneligibleTierError / UNSUPPORTED_CLIENT (free-tier 廃止).
- Codex CLI: `scripts/ai/run_codex.sh` exit 75 = usage-limit cooldown (until epoch 1782609660, ~17h out).

Per the Worker Non-Response Fallback Policy, Claude Code performed BOTH the implementation (Gemini's role)
and the verification/gates (Codex's role) directly.

実装内容: 設定メニュー(/settings) を追加し、言語・標準時間(タイムゾーン)・子どもの名前を設定できるように
した。設定は localStorage に永続化（言語は既存 i18n の `tpr.lang`、タイムゾーン=`tpr.timezone`、
子どもの名前=`tpr.childName`）。さらに、文字起こし後のサーバ側タスク登録を「設定した言語」で生成するよう、
写真アップロードのリクエストに `language` を載せて end-to-end で伝播し、タスク分割 LLM プロンプトに
出力言語指示を追加した（未指定時は ja 既定で後方互換）。

## Changed Files
- `frontend/src/settings/settingsContextValue.ts` — 新規。AppSettings 型 / SettingsContext / DEFAULT_TIMEZONE / TIMEZONE_OPTIONS。
- `frontend/src/settings/SettingsContext.tsx` — 新規。timezone/childName を localStorage 永続化する Provider。
- `frontend/src/settings/useSettings.ts` — 新規。useSettings フック。
- `frontend/src/pages/SettingsPage.tsx` — 新規。言語(select)/標準時間(select)/子どもの名前(input)の設定画面。
- `frontend/src/App.tsx` — SettingsProvider でラップ / SettingsIcon / nav に「設定」/ `/settings` ルート追加。
- `frontend/src/i18n/messages.ts` — ja/en に `nav.settings` + `settings.*` キー追加。
- `frontend/src/api/index.ts` — `uploadAttachment(infoId, file, language?)`。language 指定時に `?language=` を付与。
- `frontend/src/pages/AutoRegisterPage.tsx` — `useI18n().lang` を uploadAttachment に渡す。
- `backend/app/routers/attachments.py` — `upload_attachment` に query `language="ja"`、`process_ocr` /
  `_promote_processing_draft` に language を伝播、`build_task_drafts(..., language=language)`。
- `backend/app/extraction.py` — `_LANGUAGE_NAMES`、`_llm_tasks(raw_text, language="ja")` に出力言語指示、
  `build_task_drafts(..., language="ja")` で `_llm_tasks` に転送。
- `backend/tests/test_extraction.py` — language 伝播/プロンプト言語指示の3テスト追加。
- `frontend/e2e/scenarios.spec.ts` — S10（設定画面の表示＋再読込で永続化）追加。

## Commands Run
- backend: `ruff check app` → 0、`python -m pytest -q` → 131 passed
- frontend: `npm run lint` → 0、`npm run build` (tsc -b && vite build) → 0、`npm run e2e` → 15 passed

## Acceptance Criteria
- [x] 設定メニュー(nav)＋設定画面(/settings)が追加され、言語・標準時間(タイムゾーン)・子どもの名前を設定できる
- [x] 設定が永続化される（localStorage、language は既存 i18n と整合）
- [x] 文字起こし後のタスク登録が設定言語で生成される（upload→background task に language 伝播 + LLM プロンプト言語指示）
- [x] 既存挙動の後方互換（language 未指定→ja）
- [x] gate: ruff0 / pytest131 / eslint0 / build0 / e2e15

## Risks
- backend clock の APP_TIMEZONE はグローバル env（per-request ではない）。設定画面のタイムゾーンは保存値で、
  サーバの `today()` を変えるところまでは結線していない（スコープ外）。
- 子どもの名前は現状フォーム保存のみ（下流の利用先は未指定のため表示/保存のみ）。
- 設定言語のタスク登録への反映は LLM 出力に依存。LLM 不可/失敗時は従来通り単一 draft フォールバック。
- 本番反映には再デプロイが必要。

## Next Action
READY_FOR_REVIEW
