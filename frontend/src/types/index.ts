export interface Attachment {
  id: number;
  info_id: number;
  original_filename: string;
  mime_type: string;
  file_size: number;
  created_at: string;
}

export interface NurseryInfo {
  id: number
  title: string
  info_type: string
  content: string
  date?: string
  event_date?: string
  due_date?: string
  items?: string
  status: string
  priority: string
  tags?: string
  memo?: string
  registration_state?: string
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
  status?: string
  priority?: string
  tags?: string
  memo?: string
  registration_state?: string
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
}

// 能動リマインド (SOT-1080 / 提案5-A)
export type ReminderUrgency = 'overdue' | 'today' | 'soon' | 'upcoming'

export interface ReminderItem {
  info_id: number | string
  title: string
  info_type: string
  kind: 'deadline' | 'event' | 'belongings'
  target_date: string
  days_until: number
  urgency: ReminderUrgency
  status: string
  priority: string
  message: string
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
