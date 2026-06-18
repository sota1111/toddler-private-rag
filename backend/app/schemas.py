import datetime
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Union

class AttachmentResponse(BaseModel):
    id: Union[int, str]
    info_id: Union[int, str]
    original_filename: str
    mime_type: str
    file_size: int
    ocr_status: str = "pending"
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class NurseryInfoBase(BaseModel):
    title: str
    info_type: str
    content: str
    date: Optional[datetime.date] = None
    event_date: Optional[datetime.date] = None
    due_date: Optional[datetime.date] = None
    items: Optional[str] = None
    status: Optional[str] = "未対応"
    priority: Optional[str] = "普通"
    tags: Optional[str] = None
    memo: Optional[str] = None

class NurseryInfoCreate(NurseryInfoBase):
    pass

class NurseryInfoUpdate(BaseModel):
    title: Optional[str] = None
    info_type: Optional[str] = None
    content: Optional[str] = None
    date: Optional[datetime.date] = None
    event_date: Optional[datetime.date] = None
    due_date: Optional[datetime.date] = None
    items: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[str] = None
    memo: Optional[str] = None

class NurseryInfoResponse(NurseryInfoBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    attachments: List[AttachmentResponse] = []

    model_config = ConfigDict(from_attributes=True)


# --- RAG (ベクトル検索＋LLM回答生成) ---

class RagQuery(BaseModel):
    query: str
    top_k: int = 4


class RagSource(BaseModel):
    info_id: Optional[Union[int, str]] = None
    title: str
    source: str
    score: float
    filename: Optional[str] = None  # 添付ファイル名 (source=="ocr" の場合)
    label: Optional[str] = None  # 出典表示用ラベル (タイトル + 添付ファイル名)


class RagSearchResponse(BaseModel):
    query: str
    sources: List[RagSource] = []


class RagAnswer(BaseModel):
    answer: str
    sources: List[RagSource] = []
