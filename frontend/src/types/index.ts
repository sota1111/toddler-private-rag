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
}

export interface RagSource {
  info_id?: number | string | null
  title: string
  source: string // "content" | "ocr"
  score: number
  filename?: string | null
  label?: string | null
}

export interface RagAnswer {
  answer: string
  sources: RagSource[]
}
