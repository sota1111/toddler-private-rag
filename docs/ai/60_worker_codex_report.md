# Worker Report — Task Check + Verification (SOT-1274)

## Fallback Disclosure (audit sink)
Codex worker was non-responsive on this run (usage-limit cooldown, exit 75). Per the
Worker Non-Response Fallback Policy, Claude Code performed the initial task check and the
verification (lint/tests) directly.

## Summary
SOT-1274 is actionable as a single-file FIX. 種別（`info_type`）の自動分類は
`backend/app/tagging.py` の LLM プロンプト（`_llm_suggest`）＋ヒューリスティック fallback
（`_heuristic`）で行われる。現状プロンプトは種別名の羅列のみで定義・判別基準・例が無く、
曖昧ケース（提出物 vs 持ち物 vs お知らせ vs 掲示）で誤分類しやすい。分類プロンプトに
定義・優先順位・few-shot を追加して精度を改善した。

## Classification Paths
- info_type プロンプト: `backend/app/tagging.py` `_llm_suggest`（改善対象）
- ヒューリスティック fallback: `backend/app/tagging.py` `_heuristic`（不変）
- 別系統 `backend/app/extraction.py` `extract_categories` は本文整理用カテゴリ抽出で、
  本 Issue の「種別の分類」とは別軸のため対象外。
- フロント `frontend/src/pages/infoFormOptions.ts` の `INFO_TYPES` と同期維持。

## Commands Run
- `ruff check app/tagging.py` → All checks passed (exit 0)
- `python -m pytest tests/test_tagging_hybrid.py -q` → 4 passed
- `python -m pytest -q` (full backend) → 111 passed

## Acceptance Criteria
- [x] 分類プロンプトを改善（各種別の定義 + 判別優先順位 + few-shot 例）
- [x] `INFO_TYPES` はフロントと一致／全テスト green

## Risks
- 実環境精度の改善は Gemini 応答に依存。再デプロイで反映。テスト経路（ヒューリスティック）は不変。

## Next Action
READY_FOR_REVIEW
