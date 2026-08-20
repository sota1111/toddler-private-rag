from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Union

from .. import safety_guard, schemas
from ..repository import CareProfileRepository, get_care_profile_repository
from ..routers.auth import get_current_user

# SOT-2729: 子どもごとの個別配慮プロファイル(care_profile) の登録・取得・更新・削除。
# owner 分離は repository 層(get_care_profile_repository)で担保する。
router = APIRouter(
    prefix="/care-profiles",
    tags=["care-profiles"],
)


def _with_freshness(profile) -> schemas.CareProfileResponse:
    """ORM/辞書のプロファイルを応答へ変換し、SOT-2736 の鮮度警告を付与する。

    最終更新(``updated_at``)から一定期間を超えていれば「情報が古い可能性・見直しを」
    を ``stale_warning`` に載せる（新しい/判定不能なら None のまま）。
    """
    resp = schemas.CareProfileResponse.model_validate(profile)
    resp.stale_warning = safety_guard.profile_freshness_warning(resp.updated_at)
    return resp


@router.get("", response_model=List[schemas.CareProfileResponse])
def list_care_profiles(
    child_id: Optional[str] = None,
    repo: CareProfileRepository = Depends(get_care_profile_repository),
    current_user: str = Depends(get_current_user),
):
    # child_id クエリで特定の子どものプロファイルに絞り込める(照合層で利用)。
    return [_with_freshness(p) for p in repo.list(child_id=child_id)]


@router.get("/{id}", response_model=schemas.CareProfileResponse)
def get_care_profile(
    id: Union[int, str],
    repo: CareProfileRepository = Depends(get_care_profile_repository),
    current_user: str = Depends(get_current_user),
):
    profile = repo.get(id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Care profile not found")
    return _with_freshness(profile)


@router.post("", response_model=schemas.CareProfileResponse)
def create_care_profile(
    payload: schemas.CareProfileCreate,
    repo: CareProfileRepository = Depends(get_care_profile_repository),
    current_user: str = Depends(get_current_user),
):
    child_id = (payload.child_id or "").strip()
    if not child_id:
        raise HTTPException(status_code=422, detail="child_id is required")
    return _with_freshness(
        repo.create(
            schemas.CareProfileCreate(
                child_id=child_id,
                allergens=payload.allergens,
                care_categories=payload.care_categories,
                free_text=payload.free_text,
                severity_note=payload.severity_note,
            )
        )
    )


@router.put("/{id}", response_model=schemas.CareProfileResponse)
def update_care_profile(
    id: Union[int, str],
    payload: schemas.CareProfileUpdate,
    repo: CareProfileRepository = Depends(get_care_profile_repository),
    current_user: str = Depends(get_current_user),
):
    profile = repo.update(id, payload)
    if profile is None:
        raise HTTPException(status_code=404, detail="Care profile not found")
    return _with_freshness(profile)


@router.delete("/{id}")
def delete_care_profile(
    id: Union[int, str],
    repo: CareProfileRepository = Depends(get_care_profile_repository),
    current_user: str = Depends(get_current_user),
):
    if not repo.delete(id):
        raise HTTPException(status_code=404, detail="Care profile not found")
    return {"deleted": True}
