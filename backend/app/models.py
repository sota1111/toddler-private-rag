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
    # SOT-1562: 基になった登録写真レコードへの参照。写真の文字起こしから分解生成したタスク
    # (および締切調査の付随タスク)に元写真レコードの id を保持させ、タスク詳細から元写真へ
    # 遷移できるようにする。nullable（手動追加/既存タスクは NULL = 参照なし）。
    source_info_id = Column(String(64), nullable=True, index=True)
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
    # 献立表（給食メニュー）を日付ごとに構造化した JSON（menu-calendar 機能）。
    # {"month":"YYYY-MM","days":[{date, weekday, lunch[], main_ingredients{...}, nutrition{...}}...]}。
    # 予定/タスクではないためカレンダーの「献立」モードからのみ参照され、一覧には出ない。
    menu_json = Column(JSON, nullable=True, default=None)

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
    # SOT-1552: 子どもが所属する組/クラス（例「ひまわり組」「さくらクラス」）。
    # 任意入力。additive/nullable なので既存行は None（組/クラス未設定）のまま。
    group_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CareProfile(Base):
    """SOT-2729: 子どもごとの個別配慮プロファイル。

    子ども一人ひとりの個別配慮情報（アレルゲン・配慮カテゴリ・自由記述・重症度メモ）を保持し、
    後続のおたより照合層（SOT-2733）の第一級データ資産とする。既存 ``Child`` へは additive で、
    新規テーブルなので ``Base.metadata.create_all`` で自動作成される（既存行非破壊）。

    ``child_id`` は既存 ``NurseryInfo.child_id`` と同じく String 保持（SQLite/Firestore の
    双方で id 型が異なるためバックエンド非依存にし、FK 硬制約は既存方針どおり付けない）。
    """
    __tablename__ = "care_profile"

    id = Column(Integer, primary_key=True, index=True)
    # データ所有者(マルチテナント分離, SOT-1431 と同方式)。nullable/index。
    owner_id = Column(String(64), nullable=True, index=True)
    # 紐づく子ども(children.id)。String 保持(NurseryInfo.child_id と同方式)。
    child_id = Column(String(50), nullable=False, index=True)
    # 型付き属性: アレルゲン一覧・配慮カテゴリ一覧(JSON 配列)。未設定は空配列。
    allergens = Column(JSON, nullable=True, default=list)
    care_categories = Column(JSON, nullable=True, default=list)
    # 自由記述と重症度メモ。
    free_text = Column(Text, nullable=True)
    severity_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # 最終更新日。更新のたびに現在時刻へ更新する。
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class AttentionItem(Base):
    """SOT-2734: おたより登録時に生成する「要確認（この子向け）」項目。

    照合エンジン（SOT-2733 ``care_matching.match_notice``）が出す根拠付きの要確認候補を、
    おたより登録（OCR→抽出→本登録昇格）完了時に永続化し、予定/ダッシュボード/やること UI に
    根拠付きで併記するための第一級レコード。既存の「注意事項」カテゴリとは別レーンとして扱う
    （混同回避）。新規テーブルなので ``Base.metadata.create_all`` で自動作成される（既存行非破壊）。

    設計原則（親 SOT-2728 / Deliverable 12 S5）:
    - **断定しない**：``message`` は照合エンジンの契約どおり「要確認/情報不足のため要確認」のみ。
      「安全」「食べられる」等の断定は生成側で出さない。
    - **根拠必須**：``evidence`` に「該当文書箇所(span)/対応プロファイル項目/信頼度」を必ず持つ。
    - **人間が最終判断**：保護者が ``review_status`` を「確認済/非該当(誤検出)」に分類できる。
    """
    __tablename__ = "attention_item"

    id = Column(Integer, primary_key=True, index=True)
    # データ所有者(マルチテナント分離, SOT-1431 と同方式)。nullable/index。
    owner_id = Column(String(64), nullable=True, index=True)
    # 対象の子ども(children.id)。String 保持(NurseryInfo.child_id と同方式)。未設定は紐付けなし。
    child_id = Column(String(50), nullable=True, index=True)
    # 生成元となったおたより登録レコード(nursery_info.id)。String 保持(バックエンド非依存)。
    source_info_id = Column(String(64), nullable=True, index=True)
    # 種別: allergen | care_category（care_matching の KIND_*）。
    kind = Column(String(32), nullable=False, server_default="allergen")
    # 状態: attention（根拠あり要確認）/ abstain（情報不足のため要確認＝棄権）。
    status = Column(String(16), nullable=False, server_default="attention")
    # 正規形（アレルゲン/配慮カテゴリの canonical キー）。棄権時は None のことがある。
    canonical = Column(String(80), nullable=True)
    # 信頼度: high | medium | low（care_matching の CONF_*）。
    confidence = Column(String(16), nullable=False, server_default="medium")
    # 表示メッセージ（断定しない文面）。
    message = Column(Text, nullable=False)
    # 根拠3要素＋位置情報を格納する JSON（source/span/profile_item/confidence/locator）。
    evidence = Column(JSON, nullable=True, default=dict)
    # 対応プロファイル項目 {raw, canonical}。
    profile_item = Column(JSON, nullable=True, default=dict)
    # LLM 文脈確認の補足ノート（あれば）。
    llm_notes = Column(JSON, nullable=True, default=None)
    # 保護者のレビュー分類: unreviewed（未確認）/ confirmed（確認済）/ not_applicable（非該当・誤検出）。
    review_status = Column(String(20), nullable=False, server_default="unreviewed")
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SeededOwner(Base):
    """SOT-1507: 初回ログイン時に初期データをコピー配布したオーナーを記録する冪等マーカー。

    新規ユーザーが初めてログインした際に既定オーナー（sota.moro@gmail.com）の初期データを
    コピーする（案B）。一度シードしたオーナーには再コピーしないよう、ここに owner_id を残す。
    新規テーブルなので ``Base.metadata.create_all`` で自動作成される。
    """
    __tablename__ = "seeded_owners"

    owner_id = Column(String(64), primary_key=True, index=True)
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
