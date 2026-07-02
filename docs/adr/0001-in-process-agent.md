# 0001. エージェントを in-process 実装にする（ADK/Agent Engine 不使用）

- Status: Accepted
- Date: 2026-07-02
- Related: SOT-1470（バックフィル）, `backend/app/submission_agent.py`（決定1=案A）

## Context（背景）

おたよりナビの提出書類先回りエージェント（OCR→抽出→RAG→Search grounding→提出手順生成）を
どう構成するかを決める必要があった。選択肢として Google の Agent Development Kit (ADK) /
Vertex AI Agent Engine のようなマネージド・エージェント基盤に載せる案と、バックエンド
（FastAPI / Cloud Run）内に純 Python のエージェント処理として実装する案があった。

## Decision（決定）

エージェントはバックエンド内の **in-process 実装** とする（`backend/app/submission_agent.py`）。
ADK / Agent Engine には載せず、Gemini（Vertex AI）呼び出しと自前のオーケストレーションで
構成する。

## Alternatives（検討した代替案）

- ADK / Agent Engine に載せる — 追加のマネージドサービス依存・デプロイ経路・課金が増え、
  現状の単純なパイプライン（数ステップの逐次処理）には過剰。デバッグ・ローカル実行も複雑化する。
- 別マイクロサービスとして切り出す — 現時点でスケール要件が無く、Cloud Run 2 サービス構成の
  範囲で十分。運用面のオーバーヘッドが見合わない。

## Consequences（結果）

- 依存が減り、ローカル実行・テスト（pytest）・デバッグが容易。
- オーケストレーションを自前で持つため、複雑化したときに再検討の余地がある
  （その際は本 ADR を Superseded として新 ADR を起票する）。
- エージェントの入出力契約は `docs/agent-contract.md`（SOT-1470 D2）に明文化する。
