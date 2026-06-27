from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, Response
import os
import logging
from typing import Optional, Union
from .. import schemas, storage, ocr, extraction, clock
from ..privacy import redact_pii
from ..repository import (
    AttachmentRepository,
    get_attachment_repository,
    get_attachment_repo_standalone,
    get_info_repo_standalone,
    SqliteAttachmentRepository,
    SqliteInfoRepository,
)
from ..routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["attachments"],
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES = ["image/*", "application/pdf"]

async def process_ocr(
    att_id: int,
    ocr_path: str,
    content_type: str,
    cleanup_local: bool = False,
    info_id: Optional[Union[int, str]] = None,
):
    repo = get_attachment_repo_standalone()
    safe_text = ""
    structured = None
    ocr_ok = False
    try:
        ocr_text = ocr.extract_text(ocr_path, content_type)
        # 構造化抽出を生成（detected_dates / detected_items を enrich に活用する）
        structured = ocr.build_extraction(ocr_text)

        # PIIをマスクしてから保存
        safe_text = redact_pii(structured.raw_text)
        repo.set_ocr_result(att_id, ocr_text=safe_text, ocr_status="done")
        ocr_ok = True
    except Exception as e:
        logger.error(f"OCR failed for attachment {att_id}: {str(e)}")
        repo.set_ocr_result(att_id, ocr_text=None, ocr_status="failed")
    finally:
        if cleanup_local and os.path.exists(ocr_path):
            os.remove(ocr_path)

        # Close session if SQLite
        if isinstance(repo, SqliteAttachmentRepository):
            repo.db.close()

    # SOT-1293: 自動登録(processing)のレコードは、ブラウザ操作に依存せず、ここ(サーバ側)で
    # enrich(JSON生成)→Firestore永続化→draft昇格まで完了させる。OCR失敗時もフォールバック
    # タイトルで draft へ昇格し、写真付きで仮登録一覧に必ず出るようにする。
    if info_id is not None:
        _promote_processing_draft(
            info_id,
            safe_text if ocr_ok else "",
            structured if ocr_ok else None,
        )


def _promote_processing_draft(info_id, safe_text, structured):
    """processing のレコードを enrich してサーバ側で draft へ昇格する (SOT-1293)。

    対象が `registration_state == 'processing'`（自動登録の番兵）のときだけ作用する。
    通常の手動添付(registered)には一切作用しない。
    """
    info_repo = get_info_repo_standalone()
    try:
        info = info_repo.get(info_id)
        if info is None:
            return
        state = getattr(info, "registration_state", None) or "registered"
        if state != "processing":
            return

        today_iso = clock.today().isoformat()
        fallback_title = f"写真から登録（{today_iso}）"
        has_text = bool((safe_text or "").strip())
        detected_dates = getattr(structured, "detected_dates", None) if structured else None
        detected_items = getattr(structured, "detected_items", None) if structured else None

        # SOT-1307 (案B): 文字起こし結果を「タスク(行動項目)ごと」に分割し、それぞれを仮登録(draft)に
        # する。先頭タスクは元の processing レコードに割り当てて draft 昇格し（写真紐付けを維持）、
        # 残りのタスクは新規 draft レコードとして作成する。仮登録画面で各タスクを個別に編集/登録/削除できる。
        extra_ids = []
        try:
            tasks = extraction.build_task_drafts(
                safe_text or "", detected_dates, detected_items
            )
            if not tasks:
                raise ValueError("no task drafts")

            first = tasks[0]
            info_repo.update(
                info_id,
                schemas.NurseryInfoUpdate(
                    title=(first["title"] if has_text else fallback_title),
                    info_type=first["info_type"],
                    content=first["content"],
                    items=(first["items"] or None),
                    date=(first["date"] or None),
                    event_date=(first.get("event_date") or None),
                    registration_state="draft",
                ),
            )

            for task in tasks[1:]:
                try:
                    created = info_repo.create(
                        schemas.NurseryInfoCreate(
                            title=task["title"],
                            info_type=task["info_type"],
                            content=task["content"],
                            items=(task["items"] or None),
                            date=(task["date"] or None),
                            event_date=(task.get("event_date") or None),
                            status="未対応",
                            priority="普通",
                            registration_state="draft",
                        )
                    )
                    cid = getattr(created, "id", None)
                    if cid is not None:
                        extra_ids.append(cid)
                except Exception as e:  # 1タスクの失敗で全体を止めない
                    logger.warning(
                        f"Failed to create extra task draft for info {info_id}: {e}"
                    )
        except Exception as e:  # graceful degradation: 必ず先頭レコードを draft へ昇格させる
            logger.warning(
                f"Enrich failed for info {info_id}, promoting with fallback title: {e}"
            )
            info_repo.update(
                info_id,
                schemas.NurseryInfoUpdate(
                    title=fallback_title, registration_state="draft"
                ),
            )

        # draft 昇格で content が確定したので、ここでベクトル化して永続化する (SOT-1294)。
        # best-effort: 失敗しても昇格処理は成功とみなす。
        try:
            from ..rag.indexing import index_info_id

            index_info_id(info_id)
            for cid in extra_ids:
                try:
                    index_info_id(cid)
                except Exception as e:  # pragma: no cover - defensive
                    logger.warning(f"RAG index for extra task draft {cid} failed: {e}")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"RAG index after draft promote failed for info {info_id}: {e}")
    except Exception as e:
        logger.error(f"Failed to promote processing draft for info {info_id}: {e}")
    finally:
        if isinstance(info_repo, SqliteInfoRepository):
            db = getattr(info_repo, "db", None)
            if db is not None:
                db.close()

@router.post("/info/{info_id}/attachments", response_model=schemas.AttachmentResponse)
async def upload_attachment(
    info_id: Union[int, str],
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user)
):
    # Verify NurseryInfo exists
    if not repo.info_exists(info_id):
        raise HTTPException(status_code=404, detail="NurseryInfo not found")

    # Validate content type
    content_type = file.content_type or ""
    if content_type != "application/pdf" and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type. Allowed types: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )

    # Read file and check size
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024)}MB"
        )

    # Save to storage
    backend = storage.get_storage()
    stored_filename = storage.generate_stored_filename(file.filename)
    object_key = storage.build_object_key(stored_filename)
    
    backend.save(object_key, content, content_type)

    # Create Attachment row FIRST (pending)
    db_attachment = repo.create(
        info_id=info_id,
        stored_filename=stored_filename,
        original_filename=file.filename,
        mime_type=content_type,
        file_size=file_size,
        storage_backend=backend.name,
        object_key=object_key,
        ocr_text=None,
        ocr_status="pending"
    )

    # Prepare OCR (but don't run it yet)
    ocr_path = backend.local_path_for_ocr(object_key, content)
    
    # Schedule OCR as background task
    # If backend is GCS, ocr_path is a temp file that should be cleaned up
    cleanup_local = (backend.name == "gcs")
    background_tasks.add_task(
        process_ocr,
        db_attachment.id,
        str(ocr_path),
        content_type,
        cleanup_local,
        info_id,
    )

    return db_attachment

@router.get("/attachments/{att_id}/file")
def get_attachment_file(
    att_id: Union[int, str],
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user)
):
    db_attachment = repo.get(att_id)
    if not db_attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if db_attachment.storage_backend == "gcs":
        backend = storage.get_storage()
        # Ensure we are using GCSStorage
        if isinstance(backend, storage.GCSStorage):
            # SOT-1282: stream the bytes directly instead of redirecting to a V4
            # signed URL. On Cloud Run the default compute service-account
            # credentials only carry a token (no private key), so
            # generate_signed_url() raises "you need a private key to sign
            # credentials" and the endpoint 500s -> broken image. Serving the
            # bytes inline avoids signing entirely (same UX as local storage).
            content = backend.read(db_attachment.object_key)
            return Response(
                content=content,
                media_type=db_attachment.mime_type,
                headers={
                    "Content-Disposition": f'inline; filename="{db_attachment.original_filename}"'
                },
            )
        else:
            # Fallback if config is inconsistent, though unlikely
            raise HTTPException(status_code=500, detail="Storage configuration mismatch")

    # Local storage (default)
    file_path = storage.get_file_path(db_attachment.stored_filename or db_attachment.object_key)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    # SOT-1275: serve inline so clicking an image opens it in the browser instead of
    # forcing a download (passing filename= alone sets Content-Disposition: attachment,
    # which makes window.open(..., '_blank') show a blank tab).
    return FileResponse(
        path=file_path,
        media_type=db_attachment.mime_type,
        filename=db_attachment.original_filename,
        content_disposition_type="inline",
    )

@router.delete("/attachments/{att_id}")
def delete_attachment(
    att_id: Union[int, str],
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user)
):
    db_attachment = repo.get(att_id)
    if not db_attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Delete physical file
    backend = storage.get_storage()
    backend.delete(db_attachment.object_key or db_attachment.stored_filename)

    # Delete DB row
    repo.delete(att_id)

    return {"message": "Successfully deleted"}
