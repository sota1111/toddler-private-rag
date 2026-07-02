# Architecture Decision Records (ADR)

このディレクトリは、おたよりナビ（toddler-private-rag）の重要なアーキテクチャ決定を
横断的に追跡するための ADR (Architecture Decision Record) を保管します。

これまで主要な設計判断はコードの docstring（例: `backend/app/submission_agent.py` の
「決定1=案A」）に散在しており、「なぜその設計にしたのか」を横断的に追えませんでした
（SOT-1470 D1）。ADR はその一次記録先です。

## 運用ルール

- 1 決定 = 1 ファイル。ファイル名は `NNNN-kebab-case-title.md`（連番は 0001 から）。
- 新規決定は `0000-template.md` をコピーして起票する。
- 一度 `Accepted` にした ADR は書き換えず、覆す場合は新しい ADR を追加して
  旧 ADR の Status を `Superseded by NNNN` に更新する（履歴を消さない）。
- コード上の重要な設計判断（in-process 採用、独自 RAG、never-throw 等）は、
  該当 ADR へのリンクを docstring に併記していく。

## Index

| ADR | Title | Status |
| --- | ----- | ------ |
| [0001](0001-in-process-agent.md) | エージェントを in-process 実装にする（ADK/Agent Engine 不使用） | Accepted |
| [0002](0002-custom-rag-implementation.md) | RAG を独自実装する（マネージド RAG 不使用） | Accepted |
| [0003](0003-never-throw-degradation.md) | 外部 AI 依存経路は never-throw で graceful degradation する | Accepted |
| [0004](0004-firestore-sqlite-persistence.md) | 永続化に Firestore と SQLite を併用する | Accepted |
