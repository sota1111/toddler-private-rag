import axios from 'axios';
import type {
  NurseryInfo,
  NurseryInfoCreate,
  Attachment,
  AttachmentTranscription,
  RagAnswer,
  InfoExtractDraft,
  InfoTagSuggestion,
  HybridSearchResponse,
  ReminderFeed,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

export const getInfoList = async (params?: { q?: string; info_type?: string; status?: string; tag?: string; include_attachments?: boolean }): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/', { params });
  return response.data;
};

// 本登録データ1件取得 (SOT-1217: データ一覧の詳細ページ用)
export const getInfoById = async (id: number | string): Promise<NurseryInfo> => {
  const response = await api.get(`/info/${id}`);
  return response.data;
};

export const createInfo = async (data: NurseryInfoCreate): Promise<NurseryInfo> => {
  const response = await api.post('/info/', data);
  return response.data;
};

// 既存の仮登録(draft)を部分更新する (SOT-1175: 写真アップ後の best-effort 補完用)
export const updateInfo = async (id: number | string, data: Partial<NurseryInfoCreate>): Promise<NurseryInfo> => {
  const response = await api.put(`/info/${id}`, data);
  return response.data;
};

export const deleteInfo = async (id: number | string): Promise<void> => {
  await api.delete(`/info/${id}`);
};

// 全データ削除 (SOT-1356)。全タスク + 全写真 + ストレージ実体を削除する。破壊的・不可逆。
export const deleteAllData = async (): Promise<{ deleted: number }> => {
  const response = await api.delete('/info');
  return response.data;
};

// 仮登録(draft) 一覧取得 (SOT-1113)
export const getDrafts = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/drafts');
  return response.data;
};

// 仮登録を本登録(registered)に確定する (SOT-1113)
export const finalizeInfo = async (id: number | string): Promise<NurseryInfo> => {
  const response = await api.post(`/info/${id}/finalize`);
  return response.data;
};

// 締め切り調査 (SOT-1369): 選択した項目に対し提出書類先回りエージェントを手動起動し、
// 提出準備タスク(draft)を生成する。
export const investigateDeadline = async (
  id: number | string,
): Promise<{ created: number; ids: (number | string)[] }> => {
  const response = await api.post(`/info/${id}/investigate-deadline`);
  return response.data;
};

export const uploadAttachment = async (
  infoId: number | string,
  file: File,
  // SOT-1315: 文字起こし後のタスク登録を、この言語で生成させる（未指定時はサーバ側が ja 既定）。
  language?: string,
): Promise<Attachment> => {
  const formData = new FormData();
  formData.append('file', file);
  const url = language
    ? `/info/${infoId}/attachments?language=${encodeURIComponent(language)}`
    : `/info/${infoId}/attachments`;
  const response = await api.post<Attachment>(url, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const extractInfoDraft = async (file: File): Promise<InfoExtractDraft> => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post<InfoExtractDraft>('/info/extract', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const deleteAttachment = async (attId: number | string): Promise<void> => {
  await api.delete(`/attachments/${attId}`);
};

export const getAttachmentFileUrl = (attId: number | string): string => {
  return `/api/attachments/${attId}/file`;
};

// SOT-1325: 添付の文字起こし(OCR原文)を、内容を変えず設定言語に翻訳して取得する。
export const getAttachmentTranscription = async (
  attId: number | string,
  language: string,
): Promise<AttachmentTranscription> => {
  const response = await api.get<AttachmentTranscription>(
    `/attachments/${attId}/transcription`,
    { params: { language } },
  );
  return response.data;
};

export const getToday = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/today');
  return response.data;
};

export const getTomorrow = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/tomorrow');
  return response.data;
};

export const getWeekly = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/weekly');
  return response.data;
};

export const getNextWeek = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/next-week');
  return response.data;
};

export const getPending = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/pending');
  return response.data;
};

// 能動リマインド (SOT-1080 / 提案5-A)
export const getReminders = async (horizonDays = 7): Promise<ReminderFeed> => {
  const response = await api.get<ReminderFeed>('/info/reminders', {
    params: { horizon_days: horizonDays },
  });
  return response.data;
};

export const askInfo = async (query: string, top_k = 4): Promise<RagAnswer> => {
  const response = await api.post<RagAnswer>('/info/ask', { query, top_k });
  return response.data;
};

// SOT-1039 / 提案3: 登録時AI自動タグ付け
export const suggestInfoTags = async (payload: {
  title: string;
  content: string;
  items?: string;
  info_type?: string;
}): Promise<InfoTagSuggestion> => {
  const response = await api.post<InfoTagSuggestion>('/info/suggest-tags', payload);
  return response.data;
};

// SOT-1039 / 提案6: ハイブリッド検索
export const hybridSearch = async (params: {
  q?: string;
  info_type?: string;
  status?: string;
  priority?: string;
  tag?: string;
  date_from?: string;
  date_to?: string;
  top_k?: number;
}): Promise<HybridSearchResponse> => {
  const response = await api.get<HybridSearchResponse>('/info/hybrid-search', { params });
  return response.data;
};

export default api;
