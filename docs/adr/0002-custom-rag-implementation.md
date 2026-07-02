# 0002. RAG を独自実装する（マネージド RAG 不使用）

- Status: Accepted
- Date: 2026-07-02
- Related: SOT-1470（バックフィル）, `backend/app/rag/`

## Context（背景）

お知らせ本文に対する質問応答（/ask）のために RAG が必要だった。マネージドな
Vertex AI Search / RAG Engine を使う案と、バックエンド内に独自実装する案があった。
対象データは各家庭のプライベートなお知らせで、規模は小さく、チャンク分割・ハイブリッド検索・
埋め込みキャッシュなどを細かく制御したい要件があった。

## Decision（決定）

RAG は `backend/app/rag/` 配下の **独自実装** とする。責務ごとにモジュールを分離する:
`chunking` / `hybrid`（ハイブリッド検索） / `vector_store` / `embedding_cache` /
`indexing` / `providers` / `service`。

## Alternatives（検討した代替案）

- Vertex AI Search / マネージド RAG — データ規模が小さく、マネージド基盤の固定費・
  制御性の低さ（チャンク戦略・スコアリングのチューニング）が要件に合わない。
- 外部ベクタDB（Pinecone 等）— プライベートデータの取り回しと運用コストが見合わない。

## Consequences（結果）

- チャンク戦略・ハイブリッド検索・埋め込みキャッシュを自前で最適化・評価できる
  （`backend/tests/eval/` の RAG eval で回帰を検知）。
- 検索品質の責任を自分たちで持つため、eval harness（golden 評価）が品質担保の要になる。
- 大規模化した場合はマネージド基盤への移行を再検討する余地がある。
