from fastapi import APIRouter, Depends, HTTPException
from typing import List, Union

from .. import schemas
from ..repository import ChildRepository, get_child_repository
from ..routers.auth import get_current_user

# SOT-1368: 子供(option A, 1家族で複数の子供) の登録・一覧・削除。
router = APIRouter(
    prefix="/children",
    tags=["children"],
)


@router.get("", response_model=List[schemas.ChildResponse])
def list_children(
    repo: ChildRepository = Depends(get_child_repository),
    current_user: str = Depends(get_current_user),
):
    return repo.list()


@router.post("", response_model=schemas.ChildResponse)
def create_child(
    child: schemas.ChildCreate,
    repo: ChildRepository = Depends(get_child_repository),
    current_user: str = Depends(get_current_user),
):
    name = (child.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    # SOT-1552: 組/クラスは任意。前後空白を除去し、空なら None（未設定）にする。
    group_name = (child.group_name or "").strip() or None
    return repo.create(schemas.ChildCreate(name=name, group_name=group_name))


@router.delete("/{id}")
def delete_child(
    id: Union[int, str],
    repo: ChildRepository = Depends(get_child_repository),
    current_user: str = Depends(get_current_user),
):
    if not repo.delete(id):
        raise HTTPException(status_code=404, detail="Child not found")
    return {"deleted": True}
