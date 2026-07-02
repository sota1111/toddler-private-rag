# プロンプト / モデル設定レジストリ — SOT-1466 / SOT-1474

エージェントが使うプロンプトとモデル設定を一元管理し、変更履歴を残すためのドキュメント。

## 一元管理の場所

- **プロンプト**: `backend/app/prompt_registry.py`
  - `render_prompt(key, **kwargs)` / `get_prompt(key)` でテンプレートを取得する。
  - 呼び出し側にプロンプトをベタ書きせず、レジストリ経由で参照する。
- **モデル設定**: `backend/app/ai_client.py`
  - `get_model_name()`（`GEMINI_MODEL` 優先、既定 `gemini-3.5-flash`）
  - `default_generate_config()` / `_grounded_config()`（thinking 無効化・Search grounding）
  - `prompt_registry` からも `get_model_name` を re-export し、参照点を1つにしている。

## 段階移行の方針

回帰リスクを避けるため、インラインのプロンプトはレジストリへ**段階的に**移行する。
移行時は移行前後で生成文字列が同一であることをテストで担保する
（例: `backend/tests/test_prompt_registry.py::test_registry_prompt_matches_original_inline_prompt`）。

移行済み:
- `rag_answer` — RAG `/ask` 回答プロンプト（`app/rag/providers.py` から移行）

未移行（今後 `prompt_registry` へ移行予定）:
- OCR 文字起こし（`app/ocr.py`）
- 抽出・整理（`app/extraction.py`）
- タグ付け（`app/tagging.py`）
- 提出タスク生成（`app/submission_agent.py`）
- リマインド（`app/reminders.py`）

## 変更履歴 (CHANGELOG)

プロンプトを変更したら `PROMPT_REGISTRY_VERSION` を更新し、ここに追記する。

| Version | 日付 | 変更内容 |
| --- | --- | --- |
| 1.0.0 | 2026-07-02 | レジストリ新設。`rag_answer`（RAG回答プロンプト）を移行（内容は変更なし）。 |

## 運用メモ

- モデル更新（Gemini 世代交代）や プロンプト変更の前後で、eval 回帰スイート
  （`backend/tests/test_eval_ocr.py` / `test_eval_rag.py`, SOT-1471）を実行し、
  精度指標（coverage/precision/F1/groundedness/refusal）が閾値を下回らないことを確認する。
- 詳細な運用サイクルは `docs/runbook-operations.md` を参照。
