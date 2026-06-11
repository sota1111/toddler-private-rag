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
