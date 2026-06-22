import datetime
from pydantic import BaseModel, ConfigDict, model_validator
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


# --- 登録時AI自動タグ付け (SOT-1039 / 提案3) ---

class InfoTagSuggestRequest(BaseModel):
    """登録フォームの現在の入力から自動タグ付けを依頼するリクエスト。"""
    title: str = ""
    content: str = ""
    items: Optional[str] = None
    info_type: Optional[str] = None


class InfoTagSuggestResponse(BaseModel):
    """AI/ヒューリスティックが推定した編集可能なメタデータ。"""
    info_type: str
    priority: str
    date: Optional[str] = None
    due_date: Optional[str] = None
    event_date: Optional[str] = None
    tags: List[str] = []
    source: str = "heuristic"  # "ai" | "heuristic"


# --- ハイブリッド検索 (SOT-1039 / 提案6) ---

class HybridSearchResultItem(BaseModel):
    info: NurseryInfoResponse
    score: float
    vector_score: float
    keyword_score: float
    matched_by: List[str] = []


class HybridSearchResponse(BaseModel):
    query: str
    results: List[HybridSearchResultItem] = []


# --- OCR 構造化抽出結果 ---

class DocumentExtraction(BaseModel):
    """OCR抽出結果を型安全に表す構造化スキーマ。"""
    raw_text: str = ""                       # 抽出された生テキスト（既存 ocr_text 相当）
    char_count: int = 0                      # raw_text の文字数
    is_empty: bool = True                    # 抽出テキストが空（空白のみ含む）か
    detected_dates: List[str] = []           # テキストから検出した日付文字列（ISO等の正規化文字列）
    detected_items: List[str] = []           # テキストから検出した持ち物/箇条書き項目候補

    @model_validator(mode="after")
    def derive_fields(self) -> "DocumentExtraction":
        stripped = self.raw_text.strip()
        self.char_count = len(self.raw_text)
        self.is_empty = not stripped
        return self


# --- 写真のみ登録: OCR からの登録ドラフト (SOT-829 / SOT-831) ---

class InfoExtractDraft(BaseModel):
    """画像をOCR・構造化して得た登録フォーム用ドラフト（DB未保存）。"""
    title: str
    info_type: str
    content: str
    items: Optional[str] = None
    date: Optional[str] = None                # ISO "YYYY-MM-DD" に正規化できた場合のみ
    raw_text: str = ""
    detected_dates: List[str] = []
    detected_items: List[str] = []
