from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base, SessionLocal
from .routers import info
from .seed import seed_data
from . import models

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="保育園情報アシスタント API")

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup event to seed data
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()

app.include_router(info.router, prefix="/api")

@app.get("/health")
def health_check():
    return {"status": "ok"}
