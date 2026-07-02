# 0003. 外部 AI 依存経路は never-throw で graceful degradation する

- Status: Accepted
- Date: 2026-07-02
- Related: SOT-1470（バックフィル）, SOT-1316 / SOT-1404, `backend/app/ai_client.py`

## Context（背景）

エージェント／RAG は Gemini（Vertex AI）や Google Search grounding など外部 AI に依存する。
これらは quota 超過・SDK 差異・grounding 不可などで失敗しうる。失敗のたびにユーザー体験
（お知らせ登録・質問応答）が止まるのは避けたい、という product 方針があった。

## Decision（決定）

外部 AI に依存する経路は **never-throw** を設計原則とする。失敗時は例外を送出せず、
空文字 / None / 空リスト等の安全な既定値を返し、可能なら非 grounding フォールバックへ
graceful degradation する（例: `ai_client.generate_grounded` は grounded→非 grounded→
空文字 の順で劣化）。

## Alternatives（検討した代替案）

- 失敗を例外として上位に伝播 — UX が止まる。プライベート育児支援という性質上、
  「多少劣化しても動く」方が価値が高い。
- リトライのみ（フォールバック無し）— quota/機能不可の恒常的失敗には無力。

## Consequences（結果）

- 可用性は上がるが、**サイレント劣化**（grounding 失敗・抽出0件が「正常な空応答」と
  区別できない）という観測性の弱点を生む。
- これを補うため、劣化の代理指標（grounding degraded / 抽出0件 / LLM 失敗率）を
  構造化ログ・ログベースメトリクス・アラートで可視化する（SOT-1466 / SOT-1470 D3、
  `backend/app/ai_client.py:log_llm_call`、`infra/terraform/monitoring.tf`）。
