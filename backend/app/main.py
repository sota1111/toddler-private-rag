from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from .database import engine, SessionLocal
from .routers import info, attachments
from .routers import auth as auth_router
from .seed import seed_data
from . import models
from .repository import get_database_type

logger = logging.getLogger(__name__)

if get_database_type() != "firestore":
    models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="保育園情報アシスタント API")

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
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

@app.get("/health")
def health_check():
    return {"status": "ok"}
