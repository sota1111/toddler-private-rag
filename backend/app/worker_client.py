"""SOT-1322: dispatch OCR/enrich work from the lightweight upload service to the AI worker.

The upload service (slim, fast-booting container) only persists the photo and creates the pending
Attachment record. The heavy AI work (OCR + enrich) runs on the existing backend ("AI worker")
which is triggered over HTTP here. This call is best-effort and never raises to the caller, so the
upload response stays fast even if the worker is momentarily unreachable.
"""
import os
import logging

import httpx

logger = logging.getLogger(__name__)


def dispatch_ocr(att_id, info_id=None, language: str = "ja") -> bool:
    """Trigger the AI worker to run OCR/enrich for an uploaded attachment.

    Returns True if the worker accepted the request, False otherwise. No-op (returns False) when
    ``AI_WORKER_URL`` is unset — used in local/dev where the full backend handles OCR in-process.
    """
    base = os.getenv("AI_WORKER_URL", "").rstrip("/")
    if not base:
        logger.warning("AI_WORKER_URL not set; skipping worker dispatch for attachment %s", att_id)
        return False

    url = f"{base}/internal/process-ocr"
    headers = {}
    token = os.getenv("WORKER_INVOKE_TOKEN")
    if token:
        headers["X-Worker-Token"] = token
    payload = {"att_id": att_id, "info_id": info_id, "language": language}

    try:
        # Short timeout: the worker only needs to ACCEPT and schedule its own background OCR (202).
        resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        if resp.status_code >= 400:
            logger.error("worker dispatch failed (%s): %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:  # network/timeout — never block the upload response
        logger.error("worker dispatch error for attachment %s: %s", att_id, e)
        return False
