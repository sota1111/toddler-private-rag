from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class NurseryInfo(Base):
    __tablename__ = "nursery_info"

    id = Column(Integer, primary_key=True, index=True)
    # SOT-1431: データ所有者(マルチテナント分離)。owner ごとにデータを分離する。
    # nullable で追加（既存行は NULL = 既定 owner=主ユーザー扱い）。
    owner_id = Column(String(64), nullable=True, index=True)
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
    # SOT-1407: 締め切り調査が必要なタスクか（やることリスト作成時に算出）。
    # nullable のまま追加（既存行は NULL = 未調査扱いで締め切り調査ボタン非表示）。
    needs_deadline_investigation = Column(Boolean, nullable=True, default=False)
    # SOT-1428: お気に入りフラグ。nullable で追加（既存行は NULL = 非お気に入り扱い）。
    is_favorite = Column(Boolean, nullable=True, default=False)
    # SOT-1500: アーカイブフラグ。nullable で追加（既存行は NULL = 非アーカイブ扱い）。
    # アーカイブした項目はやることリスト等のアクティブ一覧から外し、アーカイブ一覧にのみ表示する。
    is_archived = Column(Boolean, nullable=True, default=False)
    # SOT-1411: 締切調査が生成した手順タスク群をまとめるグループ識別子と、基準日(最終提出期限)からの
    # 日数オフセットを永続化する。基準日を変更したとき同グループの付随タスクをオフセット分だけ
    # まとめてずらす。全て nullable（既存行・締切調査由来でないタスクは NULL = ずらし対象外）。
    deadline_group_id = Column(String(64), nullable=True)
    deadline_offset_days = Column(Integer, nullable=True)
    deadline_base_date = Column(Date, nullable=True)
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
    # SOT-1405: 自動締切調査(写真アップロード→OCR→タスク生成)で市町村ダウンロードリンクを
    # 付与するため、アップロード時の設定済み市町村(frontend localStorage: tpr.municipality)を
    # ここに保持し、非同期の finalize/OCR 経路で再利用する（language と同じ貫通方式）。
    municipality = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    info = relationship("NurseryInfo", back_populates="attachments")

class Child(Base):
    """SOT-1368: 1家族内に登録する子供（option A）。NurseryInfo.child_id から参照される。"""
    __tablename__ = "children"

    id = Column(Integer, primary_key=True, index=True)
    # SOT-1431: データ所有者(マルチテナント分離)。nullable で追加（既存行は既定 owner 扱い）。
    owner_id = Column(String(64), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AnswerFeedback(Base):
    """SOT-1473: ユーザーからの回答フィードバック（👍/👎）。

    RAG 回答の質改善（eval データセットの育成・精度トレンド把握）の一次データを収集する。
    新規テーブルなので ``Base.metadata.create_all`` で自動作成される。
    """
    __tablename__ = "answer_feedback"

    id = Column(Integer, primary_key=True, index=True)
    # データ所有者(マルチテナント分離, SOT-1431 と同方式)。
    owner_id = Column(String(64), nullable=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    # 'up' = 👍 / 'down' = 👎
    rating = Column(String(8), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
