from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from .database import engine, Base, SessionLocal
from .routers import info, attachments
from .routers import auth as auth_router
from .seed import seed_data
from . import models

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
