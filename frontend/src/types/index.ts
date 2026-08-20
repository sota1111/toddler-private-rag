export interface Attachment {
  id: number | string;
  info_id: number | string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  created_at: string;
}

// SOT-1377: GCS direct upload の session 発行レスポンス。
export interface UploadSession {
  upload_id: number | string
  upload_url: string
  object_key: string
  expires_at: string
  method: string
  required_headers: Record<string, string>
}

// SOT-1325: 添付の文字起こし(OCR原文)を設定言語に翻訳して取得する。
export interface AttachmentTranscription {
  text: string
  ocr_status: string
  language: string
}

// SOT-1368: 1家族で複数の子供 (option A)
export interface Child {
  id: number | string
  name: string
  // SOT-1552: 所属する組/クラス（任意）。未設定は null/undefined。
  group_name?: string | null
  created_at: string
}

// SOT-2734: 要確認（この子向け）Attention Item。おたより登録時に照合エンジン(SOT-2733)が出す
// 根拠付き候補を永続化したもの。既存の注意事項カテゴリとは別レーンで併記する。
export interface AttentionEvidence {
  // 根拠3要素＋位置情報。
  source?: string // menu_json | notice_text | llm
  span?: string // 該当文書箇所
  profile_item?: string // 対応プロファイル項目（ラベル）
  confidence?: string // high | medium | low
  locator?: Record<string, unknown>
}

export type AttentionReviewStatus = 'unreviewed' | 'confirmed' | 'not_applicable'

export interface AttentionItem {
  id: number | string
  child_id?: string | null
  source_info_id?: string | null
  kind: string // allergen | care_category
  status: string // attention | abstain（情報不足のため要確認）
  canonical?: string | null
  confidence: string // high | medium | low
  message: string
  evidence?: AttentionEvidence | null
  profile_item?: Record<string, unknown> | null
  llm_notes?: string[] | null
  review_status: AttentionReviewStatus
  reviewed_at?: string | null
  created_at: string
}

// SOT-2732 / SOT-2729: 子どもごとの個別配慮プロファイル。型付き属性（アレルゲン/配慮カテゴリ）＋
// 自由記述＋重症度メモ＋最終更新日を保持する。allergens/care_categories は正規形の安定キー
// （egg, milk … / animal_contact … : SOT-2730 の辞書）で保存し、表示ラベルはフロントで解決する。
export interface CareProfile {
  id: number | string
  child_id: string
  allergens: string[]
  care_categories: string[]
  free_text?: string | null
  severity_note?: string | null
  created_at: string
  // 最終更新日（保持・表示）。未更新時は null になりうる。
  updated_at?: string | null
  // SOT-2736: 最終更新から一定期間超で「情報が古い可能性・見直しを」警告文を載せる（無ければ null）。
  stale_warning?: string | null
}

export interface CareProfileCreate {
  child_id: string
  allergens: string[]
  care_categories: string[]
  free_text?: string | null
  severity_note?: string | null
}

// 部分更新。指定フィールドのみ更新（未指定は現状維持）。
export interface CareProfileUpdate {
  allergens?: string[]
  care_categories?: string[]
  free_text?: string | null
  severity_note?: string | null
}

export interface NurseryInfo {
  id: number | string
  title: string
  info_type: string
  content: string
  date?: string
  event_date?: string
  due_date?: string
  items?: string
  child_id?: string | null
  // SOT-1562: このタスクの基になった登録写真レコードの id。写真の文字起こしから分解生成された
  // タスク（および締切調査の付随タスク）に付与される。手動追加/既存タスクは未設定。
  source_info_id?: string | number | null
  status: string
  priority: string
  tags?: string
  memo?: string
  registration_state?: string
  needs_deadline_investigation?: boolean
  // SOT-1428: お気に入りフラグ。
  is_favorite?: boolean
  // SOT-1500: アーカイブフラグ。
  is_archived?: boolean
  // SOT-1411: 締切調査タスク群のグループ識別子・基準日からの日数オフセット・基準日。
  deadline_group_id?: string | null
  deadline_offset_days?: number | null
  deadline_base_date?: string | null
  created_at: string
  updated_at: string
  attachments?: Attachment[]
}

export interface NurseryInfoCreate {
  title: string
  info_type: string
  content: string
  date?: string
  event_date?: string
  due_date?: string
  items?: string
  child_id?: string | null
  status?: string
  priority?: string
  tags?: string
  memo?: string
  registration_state?: string
  // SOT-1428: お気に入りフラグ。
  is_favorite?: boolean
  // SOT-1500: アーカイブフラグ。
  is_archived?: boolean
}

export interface ExtractedCategories {
  submissions: string[]
  belongings: string[]
  deadlines: string[]
  events: string[]
  notes: string[]
}

export interface InfoExtractDraft {
  title: string
  info_type: string
  content: string
  items?: string | null
  date?: string | null
  raw_text: string
  detected_dates: string[]
  detected_items: string[]
  categories?: ExtractedCategories
}

export interface InfoTagSuggestion {
  info_type: string
  priority: string
  date?: string | null
  due_date?: string | null
  event_date?: string | null
  tags: string[]
  source: string // "ai" | "heuristic"
}

export interface HybridSearchResultItem {
  info: NurseryInfo
  score: number
  vector_score: number
  keyword_score: number
  matched_by: string[]
}

export interface HybridSearchResponse {
  query: string
  results: HybridSearchResultItem[]
}

export interface RagSource {
  info_id?: number | string | null
  title: string
  source: string // "content" | "ocr"
  score: number
  filename?: string | null
  label?: string | null
  snippet?: string | null
}

export interface RagAnswer {
  answer: string
  sources: RagSource[]
  // SOT-2736: 責任境界・免責（サービス=支援 / 最終判断=保護者 / 専門判断=医療者・園）。
  disclaimer?: string | null
}

// 能動リマインド (SOT-1080 / 提案5-A)
export type ReminderUrgency = 'overdue' | 'today' | 'soon' | 'upcoming'

export interface ReminderItem {
  info_id: number | string
  title: string
  info_type: string
  kind: 'deadline' | 'event' | 'belongings' | 'submission'
  target_date: string
  days_until: number
  urgency: ReminderUrgency
  status: string
  priority: string
  message: string
  items?: string | null
  child_id?: string | null
}

export interface ReminderFeed {
  generated_at: string
  horizon_days: number
  counts: {
    overdue: number
    today: number
    soon: number
    upcoming: number
    total: number
  }
  items: ReminderItem[]
  digest: string
}

// --- 献立カレンダー（menu-calendar 機能）------------------------------------------
export interface MenuNutritionGroup {
  energy_kcal?: number | null
  protein_g?: number | null
  fat_g?: number | null
}

export interface MenuDay {
  date: string // ISO YYYY-MM-DD
  weekday?: string
  morning_snack: string[]
  lunch: string[]
  afternoon_snack: string[]
  main_ingredients: {
    red: string[]
    yellow: string[]
    green: string[]
    other: string[]
  }
  nutrition: {
    under3?: MenuNutritionGroup | null
    over3?: MenuNutritionGroup | null
  }
}

export interface MenuCalendarResponse {
  year: number
  month: number
  days: Record<string, MenuDay>
}
