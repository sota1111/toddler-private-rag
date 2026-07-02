# エージェント契約 (Agent Contract)

おたよりナビのエージェント／抽出経路の **入力・出力・ツール・失敗時の既定挙動** を
明文化したものです（SOT-1470 D2）。プロンプトやモデルを更新する際は、この契約
（特に出力スキーマと `schema_version`）を壊していないかを確認してください。

- 型の一次情報: `backend/app/schemas.py`
- 出力契約のバージョン: `EXTRACTION_SCHEMA_VERSION`（`schemas.py`）。抽出出力の
  後方非互換な変更時に bump する。変更履歴の考え方は下記「バージョニング」を参照。
- 設計判断の背景: `docs/adr/`（ADR）
- 失敗時の原則: never-throw（`docs/adr/0003-never-throw-degradation.md`）

## バージョニング

抽出出力スキーマ（`DocumentExtraction` / `InfoExtractDraft`）は `schema_version`
フィールドを持つ（既定値 = `EXTRACTION_SCHEMA_VERSION`）。

- 後方互換な追加（新しい任意フィールド）: bump 不要。
- 後方非互換な変更（フィールドの削除・意味変更・型変更）: `EXTRACTION_SCHEMA_VERSION`
  を bump し、本ファイルと必要なら consumer を更新する。
- consumer は `schema_version` を読んで、想定外バージョンをログ／メトリクスで検知できる。

## 1. OCR 抽出 — `DocumentExtraction`

- 入力: 生テキスト（`ocr.build_extraction(raw_text: str)`）。
- 出力: `DocumentExtraction`
  - `schema_version: str`
  - `raw_text: str` / `char_count: int` / `is_empty: bool`（`raw_text` から自動導出）
  - `detected_dates: List[str]` / `detected_items: List[str]`
- ツール: なし（正規表現ベースの決定論的処理）。
- 失敗時の既定: 空テキストなら `is_empty=True`、`detected_*` は空リスト（never-throw）。
  抽出0件は `ocr_extraction_empty` ログトークンで観測可能（SOT-1470 D3）。

## 2. 写真登録ドラフト — `InfoExtractDraft`

- 入力: 画像（`POST /api/info/extract`、`backend/app/routers/info.py`）。OCR → 構造化。
- 出力: `InfoExtractDraft`
  - `schema_version: str`
  - `title / info_type / content`（必須）、`items / date`（任意、`date` は ISO 正規化できた場合のみ）
  - `raw_text / detected_dates / detected_items`
  - `categories: ExtractedCategories`（提出物/持ち物/締切/行事予定/注意事項/その他）
- ツール: OCR、Gemini（カテゴリ抽出）。
- 失敗時の既定: 抽出不能なら空・None の安全既定で返す（never-throw）。

## 3. 提出書類 先回りエージェント — `extract_submission_documents`

- 入力: `extract_submission_documents(safe_text, detected_dates=None, language="ja", final_due_iso=None)`
  （`backend/app/submission_agent.py`）。
- 出力: `List[dict]`、各 dict:
  `{name, due_date(ISO or ""), steps(list[{name, lead_time_days}]),
    needs_company_issuance(bool|None), lead_time_days(int|None), source(str), sources(list)}`。
- ツール: Gemini による書類抽出、Google Search grounding による公式情報付与
  （`ai_client.generate_grounded_with_sources`）。
- 失敗時の既定: `safe_text` が空 / AI クライアント不可なら空リスト。1 書類の grounding
  失敗はその書類のみ空メタで継続（バッチ全体は止めない）。すべて never-throw。

## 4. RAG 質問応答 — `/ask`

- 入力: `RagQuery`（`question` 等）。
- 出力: `RagAnswer`（回答テキスト＋ `RagSource` の一覧）。コンテキスト外は推測しない
  （プロンプトは `prompt_registry` の `rag_answer`、`docs/prompt-registry.md`）。
- ツール: 独自 RAG（`backend/app/rag/`、ADR 0002）、埋め込み、ハイブリッド検索。
- 失敗時の既定: 根拠が無ければ拒否（refusal）。eval の REFUSAL ケースで担保
  （`backend/tests/eval/`）。

## 5. Search grounding — `ai_client.generate_grounded[_with_sources]`

- 入力: プロンプト文字列。
- 出力: grounded テキスト（＋ `sources`）。
- 失敗時の既定（graceful degradation, ADR 0003）:
  grounded 失敗 → 非 grounding フォールバック → それも失敗なら空文字。
  劣化は `llm_grounding_degraded` / `llm_call` / `llm_call_failed` ログトークンと
  ログベースメトリクス・アラートで観測（SOT-1466 / SOT-1470 D3、
  `infra/terraform/monitoring.tf`）。
