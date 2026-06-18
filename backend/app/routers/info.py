from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from .. import schemas, storage
from ..repository import InfoRepository, get_info_repository
from ..routers.auth import get_current_user
from ..rag.service import get_rag_service

router = APIRouter(
    prefix="/info",
    tags=["info"],
)


def _source_label(source) -> str:
    """出典の表示用ラベルを生成する (タイトル + 添付ファイル名)。"""
    if source.source == "ocr" and source.filename:
        return f"{source.title}（添付: {source.filename}）"
    return source.title


def _to_rag_source(source) -> schemas.RagSource:
    return schemas.RagSource(
        info_id=source.info_id,
        title=source.title,
        source=source.source,
        score=source.score,
        filename=source.filename,
        label=_source_label(source),
    )


# NOTE: declared before the "/{id}" route so the literal paths take precedence.
@router.post("/ask", response_model=schemas.RagAnswer)
def ask_info(
    payload: schemas.RagQuery,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """ベクトル検索で関連情報を取得し、LLMで回答を生成する (RAG)。"""
    service = get_rag_service(repo)
    result = service.answer(payload.query, top_k=payload.top_k)
    return schemas.RagAnswer(
        answer=result.answer,
        sources=[_to_rag_source(s) for s in result.sources],
    )


@router.get("/search", response_model=schemas.RagSearchResponse)
def vector_search_info(
    q: str = Query(..., description="検索クエリ"),
    top_k: int = 4,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user),
):
    """埋め込みベースのベクトル検索のみを実行し、関連チャンク（出典）を返す。"""
    service = get_rag_service(repo)
    sources = service.search(q, top_k=top_k)
    return schemas.RagSearchResponse(
        query=q,
        sources=[_to_rag_source(s) for s in sources],
    )


@router.post("/", response_model=schemas.NurseryInfoResponse)
def create_info(info: schemas.NurseryInfoCreate, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.create(info)

@router.get("/tomorrow", response_model=List[schemas.NurseryInfoResponse])
def get_tomorrow_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_tomorrow()

@router.get("/weekly", response_model=List[schemas.NurseryInfoResponse])
def get_weekly_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_weekly()

@router.get("/pending", response_model=List[schemas.NurseryInfoResponse])
def get_pending_info(repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    return repo.list_pending()

@router.get("/", response_model=List[schemas.NurseryInfoResponse])
def list_info(
    q: Optional[str] = None,
    info_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    repo: InfoRepository = Depends(get_info_repository),
    current_user: str = Depends(get_current_user)
):
    return repo.list(q=q, info_type=info_type, status=status, priority=priority, tag=tag)

@router.get("/{id}", response_model=schemas.NurseryInfoResponse)
def get_info(id: int, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.get(id)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info

@router.put("/{id}", response_model=schemas.NurseryInfoResponse)
def update_info(id: int, info: schemas.NurseryInfoUpdate, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    db_info = repo.update(id, info)
    if db_info is None:
        raise HTTPException(status_code=404, detail="Info not found")
    return db_info

@router.delete("/{id}")
def delete_info(id: int, repo: InfoRepository = Depends(get_info_repository), current_user: str = Depends(get_current_user)):
    # List attachments to delete physical files
    attachments = repo.list_attachments_for_info(id)
    
    # Delete physical files
    backend = storage.get_storage()
    for attachment in attachments:
        backend.delete(attachment.object_key or attachment.stored_filename)

    if not repo.delete(id):
        raise HTTPException(status_code=404, detail="Info not found")
        
    return {"message": "Successfully deleted"}

