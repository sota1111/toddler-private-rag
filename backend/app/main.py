from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from .database import engine, SessionLocal
from .routers import info, attachments, worker, children, feedback
from .routers import auth as auth_router
from .seed import seed_data
from . import models
from .migrations import ensure_sqlite_schema
from .repository import get_database_type

logger = logging.getLogger(__name__)

database_type = get_database_type()
if database_type != "firestore":
    models.Base.metadata.create_all(bind=engine)
if database_type == "sqlite":
    ensure_sqlite_schema(engine)

app = FastAPI(title="おたよりナビ API")

def _parse_cors_origins() -> list[str]:
    """CORS 許可オリジンを解析する（SOT-1528: 本番オリジン限定のハードニング）。

    ``allow_credentials=True`` はワイルドカード ``*`` と両立しない（資格情報付きで全オリジンを
    許可すると API が誰からでも呼べてしまう）。空白除去のうえ ``*`` は破棄し、結果が空なら
    ローカル既定にフォールバックする。
    """
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    safe = [o for o in origins if o != "*"]
    if len(safe) != len(origins):
        logger.warning(
            "CORS_ORIGINS に '*' が含まれています。allow_credentials=True と両立しないため無視します。"
        )
    return safe or ["http://localhost:5173"]


_cors_origins = _parse_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    # Auth configuration check
    auth_secret = os.getenv("AUTH_SECRET")
    firebase_api_key = os.getenv("FIREBASE_WEB_API_KEY") or os.getenv("FIREBASE_API_KEY")
    allowed_emails = os.getenv("ALLOWED_USER_EMAILS")

    missing = False
    if not firebase_api_key:
        logger.warning("FIREBASE_WEB_API_KEY / FIREBASE_API_KEY not configured")
        missing = True
    if not auth_secret:
        logger.warning("AUTH_SECRET not configured")
        missing = True
    if not allowed_emails:
        logger.warning("ALLOWED_USER_EMAILS not configured")
        missing = True

    if not missing:
        logger.info("auth config OK")

    if os.getenv("APP_ENV", "local").lower() == "production":
        return
    if get_database_type() != "firestore":
        db = SessionLocal()
        try:
            seed_data(db)
        finally:
            db.close()

app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(attachments.router, prefix="/api")
app.include_router(info.router, prefix="/api")
app.include_router(children.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
# SOT-1322: internal AI-worker endpoint (no /api prefix) called by the upload service.
app.include_router(worker.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}
