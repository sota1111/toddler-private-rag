"""SOT-2734: おたより登録時の「要確認（この子向け）」生成サービス。

照合エンジン（SOT-2733 :func:`care_matching.match_notice`）が出す根拠付き候補を、おたより登録
（OCR→抽出→本登録昇格）完了時に永続化する薄い生成層。UI（予定/ダッシュボード/やること）は
永続化された :class:`models.AttentionItem` を読み、根拠付きで併記し、保護者が確認済/非該当に
分類する（人間が最終判断）。

設計原則（親 SOT-2728 / Deliverable 12 S5）:
- **断定しない**：文面は照合エンジンの契約どおり「要確認/情報不足のため要確認」のみを載せる。
  「安全」「食べられる」等の断定表現は生成側で作らない。
- **根拠必須**：各候補の ``evidence``（該当文書箇所/対応プロファイル項目/信頼度）をそのまま保持する。
- **冪等**：同じおたより(source_info_id)を再登録したら、既存項目を消してから作り直す
  （二重生成しない）。
- **best-effort**：この生成で例外が出ても、呼び出し側（登録フロー）を止めない。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import care_matching, schemas

logger = logging.getLogger(__name__)


def candidate_to_create(
    candidate: Dict[str, Any],
    *,
    child_id: Optional[str],
    source_info_id: Optional[str],
    owner_id: Optional[str],
) -> schemas.AttentionItemCreate:
    """照合エンジンの候補 dict を :class:`schemas.AttentionItemCreate` に写像する。"""
    evidence = candidate.get("evidence") or {}
    return schemas.AttentionItemCreate(
        owner_id=owner_id,
        child_id=(str(child_id) if child_id is not None else None),
        source_info_id=(str(source_info_id) if source_info_id is not None else None),
        kind=candidate.get("kind", care_matching.KIND_ALLERGEN),
        status=candidate.get("status", care_matching.STATUS_ATTENTION),
        canonical=candidate.get("canonical"),
        confidence=evidence.get("confidence")
        or candidate.get("confidence")
        or care_matching.CONF_MEDIUM,
        message=candidate.get("message", ""),
        evidence=evidence,
        profile_item=candidate.get("profile_item") or {},
        llm_notes=candidate.get("llm_notes"),
        review_status="unreviewed",
    )


def generate_attention_items(
    *,
    info_id: Any,
    child_id: Optional[str],
    owner_id: Optional[str],
    notice_text: Optional[str],
    menu_json: Optional[Dict[str, Any]],
    care_repo: Any,
    attention_repo: Any,
    use_llm: bool = True,
) -> List[Any]:
    """おたより(本文/献立) × 対象の子の care_profile を照合し、要確認項目を永続化して返す。

    - ``child_id`` が無い（子ども未紐付け）／プロファイルが無い場合は何も作らず ``[]`` を返す。
    - 生成前に同じ ``info_id`` 由来の既存項目を削除し、再登録でも二重生成しない（冪等）。
    - ``care_matching`` はオフライン時 LLM を静かに無視し、決定論のみで同入力→同出力になる。
    """
    if child_id is None or str(child_id).strip() == "":
        return []

    profiles = care_repo.list(child_id=str(child_id))
    if not profiles:
        return []

    # 冪等化: 同じおたより由来の既存要確認項目を作り直す（再登録・再OCR に安全）。
    try:
        attention_repo.delete_by_source(info_id)
    except Exception as e:  # noqa: BLE001 - 削除失敗は生成を止めない
        logger.warning("attention delete_by_source failed for info %s: %s", info_id, e)

    created: List[Any] = []
    for profile in profiles:
        try:
            result = care_matching.match_notice(
                profile,
                notice_text=notice_text,
                menu_json=menu_json,
                use_llm=use_llm,
            )
        except Exception as e:  # noqa: BLE001 - 1プロファイルの失敗で全体を止めない
            logger.warning("care matching failed for info %s: %s", info_id, e)
            continue
        for candidate in result.get("candidates", []):
            try:
                payload = candidate_to_create(
                    candidate,
                    child_id=child_id,
                    source_info_id=info_id,
                    owner_id=owner_id,
                )
                created.append(attention_repo.create(payload))
            except Exception as e:  # noqa: BLE001 - 1件の失敗で全体を止めない
                logger.warning(
                    "attention item persist failed for info %s: %s", info_id, e
                )
    if created:
        logger.info(
            "generated %d attention item(s) for info %s (child %s)",
            len(created),
            info_id,
            child_id,
        )
    return created
