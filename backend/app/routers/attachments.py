from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, Response
import os
import logging
from typing import Optional, Union
from .. import schemas, storage, ocr, extraction, clock
from ..concurrency import run_parallel
from ..timing import time_block
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
    language: str = "ja",
):
    repo = get_attachment_repo_standalone()
    safe_text = ""
    structured = None
    ocr_ok = False
    # SOT-1374: 写真1枚あたりのOCR処理全体(OCR本体+構造化抽出+保存+事前翻訳)の所要時間を計測する。
    # 細粒度の `stage=ocr`(OCR本体)はそのまま残し、ここでは end-to-end の `process_ocr_total` を出す。
    with time_block("process_ocr_total", attachment_id=att_id):
        try:
            # SOT-1374 / D: OCR(外部API待ちが主体)の所要時間を計測する。OCR は並列化しない(指示)。
            with time_block("ocr", attachment_id=att_id) as t:
                ocr_text = ocr.extract_text(ocr_path, content_type)
                t["chars"] = len(ocr_text or "")
            # 構造化抽出を生成（detected_dates / detected_items を enrich に活用する）
            structured = ocr.build_extraction(ocr_text)

            # PIIをマスクしてから保存
            safe_text = redact_pii(structured.raw_text)
            repo.set_ocr_result(att_id, ocr_text=safe_text, ocr_status="done")
            ocr_ok = True
            # SOT-1330: 文字起こし完了直後に一度だけ翻訳して保存する（読み込みの度に翻訳しない）。
            if safe_text.strip():
                try:
                    pre_lang = language if language in ("ja", "en") else "ja"
                    repo.set_translation(
                        att_id,
                        language=pre_lang,
                        text=extraction.translate_text(safe_text, pre_lang),
                    )
                except Exception as te:
                    logger.warning("pre-translate failed for attachment %s: %s", att_id, te)
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
            language=language,
        )


def _promote_processing_draft(info_id, safe_text, structured, language="ja"):
    """processing のレコードを enrich してサーバ側で本登録(registered)へ昇格する (SOT-1293 / SOT-1324)。

    対象が `registration_state == 'processing'`（自動登録の番兵）のときだけ作用する。
    通常の手動添付(registered)には一切作用しない。

    SOT-1324: 写真(メイン)レコードは本登録(finalize)ステップを介さず直接 `registered` へ昇格する。
    （抽出タスクは従来どおり `draft` レコードのまま＝仮登録レビュー導線を維持する。）
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
        # SOT-1368 follow-up: 親(写真)レコードに紐づけた子ども(child_id)を、
        # OCRから自動生成する各タスクdraftにも引き継ぐ。未指定(None)は紐付けなし。
        parent_child_id = getattr(info, "child_id", None)
        detected_dates = getattr(structured, "detected_dates", None) if structured else None
        detected_items = getattr(structured, "detected_items", None) if structured else None

        # SOT-1318: 文字起こし結果を「写真+タイトル(登録レコード)」と「タスク(行動項目)」に分離する。
        #   - 元の processing レコード（写真添付を保持）は、全体タイトルだけを持つ登録一覧用レコードに
        #     する（event_date なし＝タスクではない）。→ 登録一覧(RegisteredListPage)にのみ出る。
        #   - 抽出したタスクはすべて新規 draft レコードにする（写真添付なし / event_date あり）。
        #     → タスク一覧(TasksPage)にのみ出る。
        # これにより同じレコードがタスク一覧と登録一覧の両方に出る問題を解消する (旧 SOT-1307 の写真紐付け)。
        # SOT-1324: 写真(メイン)レコードは本登録(finalize)を介さず直接 `registered` で昇格する。
        extra_ids = []
        try:
            # SOT-1374 / B: 全体タイトル抽出(build_draft_fields)とタスク分割(build_task_drafts)は
            # 同じ safe_text に対する互いに独立した LLM 呼び出しなので、並列実行して待ち時間を縮める。
            # （OCR は並列化しない。並列化は LLM/埋め込みのみ、という指示に従う。）
            with time_block("llm_extract_parallel"):
                overall, tasks = run_parallel(
                    lambda: extraction.build_draft_fields(
                        safe_text or "", detected_dates, detected_items, language=language
                    ),
                    lambda: extraction.build_task_drafts(
                        safe_text or "", detected_dates, detected_items, language=language
                    ),
                )

            # 写真+タイトルの登録レコード: 全体タイトル/種別/本文を作り、event_date は持たせない。
            info_repo.update(
                info_id,
                schemas.NurseryInfoUpdate(
                    title=(overall["title"] if has_text else fallback_title),
                    info_type=overall["info_type"],
                    content=overall["content"],
                    items=(overall["items"] or None),
                    date=(overall["date"] or None),
                    event_date=None,  # 登録レコードはタスクではないので予定日を持たせない
                    registration_state="registered",  # SOT-1324: 本登録を介さず直接登録
                ),
            )

            # タスクは別レコードに分離する（写真添付なし）。
            for task in tasks:
                try:
                    created = info_repo.create(
                        schemas.NurseryInfoCreate(
                            title=task["title"],
                            info_type=task["info_type"],
                            content=task["content"],
                            items=(task["items"] or None),
                            date=(task["date"] or None),
                            event_date=(task.get("event_date") or None),
                            child_id=parent_child_id,  # SOT-1368: 親写真の子どもを引き継ぐ
                            status="未確認",
                            priority="普通",
                            registration_state="draft",
                        )
                    )
                    cid = getattr(created, "id", None)
                    if cid is not None:
                        extra_ids.append(cid)
                except Exception as e:  # 1タスクの失敗で全体を止めない
                    logger.warning(
                        f"Failed to create task draft for info {info_id}: {e}"
                    )

            # SOT-1369: 提出書類先回りエージェント(SOT-1316)の自動起動はここから撤去した。
            # 締め切り調査は、一覧から項目を選んで「締め切り調査」ボタンを押したときに
            # POST /info/{id}/investigate-deadline 経由で手動トリガするよう変更した。
        except Exception as e:  # graceful degradation: 必ず元レコードを登録(registered)へ昇格させる
            logger.warning(
                f"Enrich failed for info {info_id}, promoting with fallback title: {e}"
            )
            info_repo.update(
                info_id,
                schemas.NurseryInfoUpdate(
                    title=fallback_title, registration_state="registered"  # SOT-1324
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
    language: str = "ja",
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
        language,
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

@router.get(
    "/attachments/{att_id}/transcription",
    response_model=schemas.AttachmentTranscriptionResponse,
)
def get_attachment_transcription(
    att_id: Union[int, str],
    language: str = "ja",
    repo: AttachmentRepository = Depends(get_attachment_repository),
    current_user: str = Depends(get_current_user),
):
    """添付の文字起こし(OCR原文)を、内容を変えず設定言語に翻訳して返す (SOT-1325)。

    `content`(LLMで再構成済み)ではなく生の `ocr_text` を対象とし、言語のみ変換する。
    """
    db_attachment = repo.get(att_id)
    if not db_attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    lang = language if language in ("ja", "en") else "ja"
    ocr_text = getattr(db_attachment, "ocr_text", None) or ""
    ocr_status = getattr(db_attachment, "ocr_status", "pending") or "pending"

    # SOT-1330: 保存済みの翻訳があれば再利用する。無ければ翻訳して保存してから返す
    # （遅延キャッシュ）。これにより読み込みの度に翻訳を実行しない。
    translations = getattr(db_attachment, "translations", None) or {}
    if lang in translations and translations[lang]:
        translated = translations[lang]
    elif ocr_text.strip():
        translated = extraction.translate_text(ocr_text, lang)
        try:
            repo.set_translation(att_id, language=lang, text=translated)
        except Exception as ce:
            logger.warning("cache-fill translation failed for attachment %s: %s", att_id, ce)
    else:
        translated = ""

    return schemas.AttachmentTranscriptionResponse(
        text=translated,
        ocr_status=ocr_status,
        language=lang,
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
