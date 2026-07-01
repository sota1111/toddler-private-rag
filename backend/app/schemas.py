import datetime
from pydantic import BaseModel, ConfigDict, model_validator, field_validator
from typing import Optional, List, Union


def _empty_str_to_none(value):
    """空文字・空白のみの文字列を None に正規化する。

    フロントの登録フォームは未入力の日付を空文字 "" で送るため、
    Optional[datetime.date] のフィールドがそのままだと Pydantic の
    日付パースで 422 になる。空入力＝未設定として None に倒す。
    """
    if isinstance(value, str) and value.strip() == "":
        return None
    return value

class AttachmentResponse(BaseModel):
    id: Union[int, str]
    info_id: Union[int, str]
    original_filename: str
    mime_type: str
    file_size: int
    ocr_status: str = "pending"
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class UploadSessionRequest(BaseModel):
    """SOT-1377: GCS direct upload の session 発行リクエスト。

    画像本体は送らず、ファイルのメタ情報だけを送って署名付き PUT URL を受け取る。
    """
    filename: str
    content_type: str
    file_size: Optional[int] = None
    language: str = "ja"


class UploadSessionResponse(BaseModel):
    """session 発行の応答。ブラウザはこの upload_url へ画像本体を直接 PUT する。"""
    upload_id: Union[int, str]
    upload_url: str
    object_key: str
    expires_at: datetime.datetime
    method: str = "PUT"
    required_headers: dict = {}


class AttachmentTranscriptionResponse(BaseModel):
    """添付の文字起こし(OCR原文)を設定言語に翻訳して返す (SOT-1325)。"""
    text: str = ""
    ocr_status: str = "pending"
    language: str = "ja"

# --- 子供 (SOT-1368: option A, 1家族で複数の子供) ---

class ChildBase(BaseModel):
    name: str


class ChildCreate(ChildBase):
    pass


class ChildResponse(ChildBase):
    id: Union[int, str]
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
    # SOT-1368: 紐づく子供のID(option A)。未指定は紐付けなし(後方互換)。
    child_id: Optional[str] = None
    status: Optional[str] = "未確認"
    # 仮登録(draft) / 本登録(registered)。省略時は本登録。
    registration_state: Optional[str] = "registered"
    # SOT-1407: 締め切り調査が必要なタスクか（やることリスト作成時に算出）。
    needs_deadline_investigation: Optional[bool] = False
    # SOT-1428: お気に入りフラグ。
    is_favorite: Optional[bool] = False
    # SOT-1411: 締切調査が生成した手順タスク群のグループ識別子・基準日からの日数オフセット・基準日。
    deadline_group_id: Optional[str] = None
    deadline_offset_days: Optional[int] = None
    deadline_base_date: Optional[datetime.date] = None
    priority: Optional[str] = "普通"
    tags: Optional[str] = None
    memo: Optional[str] = None

    _normalize_dates = field_validator(
        "date", "event_date", "due_date", "deadline_base_date", mode="before"
    )(_empty_str_to_none)

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
    child_id: Optional[str] = None
    status: Optional[str] = None
    registration_state: Optional[str] = None
    needs_deadline_investigation: Optional[bool] = None
    # SOT-1428: お気に入りフラグ。
    is_favorite: Optional[bool] = None
    # SOT-1411
    deadline_group_id: Optional[str] = None
    deadline_offset_days: Optional[int] = None
    deadline_base_date: Optional[datetime.date] = None
    priority: Optional[str] = None
    tags: Optional[str] = None
    memo: Optional[str] = None

    _normalize_dates = field_validator(
        "date", "event_date", "due_date", "deadline_base_date", mode="before"
    )(_empty_str_to_none)

class NurseryInfoResponse(NurseryInfoBase):
    id: Union[int, str]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    attachments: List[AttachmentResponse] = []

    model_config = ConfigDict(from_attributes=True)


# 締切調査（提出書類先回りエージェント）の手動起動リクエスト（SOT-1405）。
# municipality は登録/設定値の市町村。市区町村窓口/公式HPから様式をDLする手順がある場合、
# その市町村のダウンロードページ検索リンクを生成タスク本文へ付与するために使う。
class InvestigateDeadlineRequest(BaseModel):
    municipality: Optional[str] = None


# SOT-1411: 締切調査タスクの基準日(最終提出期限)変更リクエスト。基準日を変えると、同じ
# deadline_group_id を持つ付随タスクを、各タスクの deadline_offset_days(基準日から何日手前か)を
# 使ってまとめて再計算(ずらし)する。
class RescheduleDeadlineRequest(BaseModel):
    base_date: datetime.date

    _normalize_dates = field_validator("base_date", mode="before")(_empty_str_to_none)


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
    snippet: Optional[str] = None  # 根拠となる元テキストの抜粋 (SOT-1094)


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


# --- 5カテゴリ構造化抽出 (SOT-1085 / SOT-1092) ---

class ExtractedCategories(BaseModel):
    """お知らせから抽出したタイトル＋保護者の行動5カテゴリ。"""
    title: str = ""               # お知らせ全体の簡潔なタイトル (SOT-1292)
    submissions: List[str] = []   # 提出物
    belongings: List[str] = []    # 持ち物
    deadlines: List[str] = []     # 締切
    events: List[str] = []        # 行事予定
    notes: List[str] = []         # 注意事項
    other: List[str] = []         # その他（どのカテゴリにも該当しない事項。RAGから漏らさないため SOT-1294）


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
    categories: ExtractedCategories = ExtractedCategories()  # 提出物/持ち物/締切/行事予定/注意事項


# --- 能動リマインド (SOT-1080 / 提案5-A) ---

class ReminderItem(BaseModel):
    """締切/行事/持ち物から導出した緊急度付きリマインド1件。"""
    info_id: Union[int, str]
    title: str
    info_type: str
    kind: str            # "deadline" | "event" | "belongings" | "submission"
    target_date: str     # ISO YYYY-MM-DD
    days_until: int
    urgency: str         # "overdue" | "today" | "soon" | "upcoming"
    status: str
    priority: str
    message: str
    items: Optional[str] = None  # SOT-1397: 持ち物リマインドの持ち物テキスト（フロントで言語化に使用）


class ReminderFeed(BaseModel):
    """能動リマインドフィード（一覧 + 緊急度別件数 + 通知向けダイジェスト）。"""
    generated_at: str
    horizon_days: int
    counts: dict = {}    # {"overdue":n,"today":n,"soon":n,"upcoming":n,"total":n}
    items: List[ReminderItem] = []
    digest: str = ""


class ReminderDigest(BaseModel):
    """通知配信向けのダイジェストのみを返す軽量レスポンス。"""
    generated_at: str
    horizon_days: int
    total: int
    digest: str
