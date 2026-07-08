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

// SOT-1593: 未保存ファイル(PDF/画像)の文字起こし(OCR原文)のみ。確認フェーズで登録前に中身を確認する。
export interface InfoTranscription {
  text: string
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
