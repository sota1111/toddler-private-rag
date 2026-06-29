from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class NurseryInfo(Base):
    __tablename__ = "nursery_info"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    info_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    date = Column(Date, nullable=True)
    event_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    items = Column(Text, nullable=True)
    # SOT-1368: どの子供に紐づくか（option A: 1家族で複数の子供）。未設定(既存データ)は紐付けなし。
    child_id = Column(String(50), nullable=True)
    status = Column(String(20), default="未確認")
    # 仮登録(draft) / 本登録(registered) の区分。既存(未設定)データは registered 扱い。
    registration_state = Column(String(20), nullable=False, server_default="registered", default="registered")
    priority = Column(String(10), default="普通")
    tags = Column(Text, nullable=True)
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    attachments = relationship("Attachment", back_populates="info", cascade="all, delete-orphan")

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    info_id = Column(Integer, ForeignKey("nursery_info.id"), index=True, nullable=False)
    stored_filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    storage_backend = Column(String, nullable=False, server_default="local")
    object_key = Column(String, nullable=True)
    ocr_text = Column(Text, nullable=True, default=None)
    ocr_status = Column(String(20), nullable=False, server_default="pending")
    # SOT-1330: 文字起こし(OCR原文)の翻訳を言語ごとに一度だけ保存して再利用する
    # （読み込みの度に翻訳しない）。例: {"ja": "...", "en": "..."}
    translations = Column(JSON, nullable=True, default=None)
    # SOT-1377: GCS direct-upload では OCR が finalize イベント経由で非同期起動するため、
    # session 発行時のリクエスト言語をここに保持しておき finalize 時に再利用する。
    language = Column(String(8), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    info = relationship("NurseryInfo", back_populates="attachments")

class Child(Base):
    """SOT-1368: 1家族内に登録する子供（option A）。NurseryInfo.child_id から参照される。"""
    __tablename__ = "children"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
