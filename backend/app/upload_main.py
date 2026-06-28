"""SOT-1322: slim ASGI entrypoint for the lightweight upload Cloud Run service.

This app mounts ONLY the slim upload router (+ health + CORS). It intentionally does NOT import the
info/attachments routers, seed, migrations, or any AI/OCR module, so the container starts fast and
the image (built from backend/Dockerfile.upload) carries no tesseract / Vision / genai dependencies.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

from .routers import upload

logger = logging.getLogger(__name__)

app = FastAPI(title="おたよりナビ Upload API")

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok"}
