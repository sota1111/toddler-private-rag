from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Union

from .. import schemas
from ..repository import AttentionItemRepository, get_attention_item_repository
from ..routers.auth import get_current_user

# SOT-2734: おたより登録時に生成した「要確認（この子向け）」項目の一覧・レビュー分類 API。
# 生成そのものは登録フロー(routers/attachments._promote_processing_draft)で行い、ここでは
# 予定/ダッシュボード/やること UI からの参照と、保護者の確認済/非該当分類のみを担う。
# owner 分離は repository 層(get_attention_item_repository)で担保する。
router = APIRouter(
    prefix="/attention-items",
    tags=["attention-items"],
)


@router.get("", response_model=List[schemas.AttentionItemResponse])
def list_attention_items(
    child_id: Optional[str] = None,
    source_info_id: Optional[str] = None,
    review_status: Optional[str] = None,
    repo: AttentionItemRepository = Depends(get_attention_item_repository),
    current_user: str = Depends(get_current_user),
):
    # child_id / source_info_id / review_status で絞り込める（UI のレーン表示・根拠導線で利用）。
    if review_status is not None and review_status not in schemas.ATTENTION_REVIEW_STATES:
        raise HTTPException(status_code=422, detail="invalid review_status")
    return repo.list(
        child_id=child_id,
        source_info_id=source_info_id,
        review_status=review_status,
    )


@router.get("/{id}", response_model=schemas.AttentionItemResponse)
def get_attention_item(
    id: Union[int, str],
    repo: AttentionItemRepository = Depends(get_attention_item_repository),
    current_user: str = Depends(get_current_user),
):
    item = repo.get(id)
    if item is None:
        raise HTTPException(status_code=404, detail="Attention item not found")
    return item


@router.patch("/{id}/review", response_model=schemas.AttentionItemResponse)
def review_attention_item(
    id: Union[int, str],
    payload: schemas.AttentionItemReviewUpdate,
    repo: AttentionItemRepository = Depends(get_attention_item_repository),
    current_user: str = Depends(get_current_user),
):
    # 保護者が「確認済 / 非該当（誤検出） / 未確認へ戻す」を記録する（人間が最終判断）。
    item = repo.set_review_status(id, payload.review_status)
    if item is None:
        raise HTTPException(status_code=404, detail="Attention item not found")
    return item
