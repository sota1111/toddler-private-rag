# Worker Report — SOT-1274

## Summary
SOT-1274「分類が上手くできていない」: `info_type`（種別）自動分類の精度向上のため、
`backend/app/tagging.py` の LLM 分類プロンプト（`_llm_suggest`）を改善した。

**Fallback disclosure (audit sink):** Gemini worker was non-responsive on this run
(`IneligibleTierError: UNSUPPORTED_CLIENT` / exit 75). Per the Worker Non-Response
Fallback Policy, Claude Code performed the implementation directly.

## Changed Files
- `backend/app/tagging.py` — `_llm_suggest` 内の分類プロンプトを刷新。8 種別それぞれの定義、
  複数該当時の判別優先順位（提出物 > 持ち物 > 行事 > 給食 > 休園変更 > 掲示/資料 > お知らせ）、
  priority の判定基準、提出物/持ち物/行事を区別する few-shot 例 3 件を追加。
  `INFO_TYPES`/`PRIORITY_TYPES` 定数・関数シグネチャ・JSON 出力形状・`_heuristic` は不変。

## Commands Run
- `python -c "import ast; ast.parse(...)"` → OK
- `ruff check app/tagging.py` → All checks passed
- `python -m pytest tests/test_tagging_hybrid.py -q` → 4 passed

## Acceptance Criteria
- [x] 分類プロンプトに各種別の定義・判別ルール・優先順位・few-shot 例を追加
- [x] `INFO_TYPES` はフロント `infoFormOptions.ts` と一致を維持／既存テスト green

## Risks
- ヒューリスティック経路（AI 無効時／テスト）は不変なので回帰なし。実環境の精度向上は
  Gemini 応答に依存し、再デプロイ後に効果が出る。

## Next Action
READY_FOR_REVIEW
