import axios from 'axios';
import type { NurseryInfo, NurseryInfoCreate, Attachment, RagAnswer, InfoExtractDraft } from '../types';

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

export const getInfoList = async (params?: { q?: string; info_type?: string; status?: string; tag?: string }): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/', { params });
  return response.data;
};

export const createInfo = async (data: NurseryInfoCreate): Promise<NurseryInfo> => {
  const response = await api.post('/info/', data);
  return response.data;
};

export const deleteInfo = async (id: number): Promise<void> => {
  await api.delete(`/info/${id}`);
};

export const uploadAttachment = async (infoId: number, file: File): Promise<Attachment> => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post<Attachment>(`/info/${infoId}/attachments`, formData, {
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

export const deleteAttachment = async (attId: number): Promise<void> => {
  await api.delete(`/attachments/${attId}`);
};

export const getAttachmentFileUrl = (attId: number): string => {
  return `/api/attachments/${attId}/file`;
};

export const getTomorrow = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/tomorrow');
  return response.data;
};

export const getWeekly = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/weekly');
  return response.data;
};

export const getPending = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/pending');
  return response.data;
};

export const askInfo = async (query: string, top_k = 4): Promise<RagAnswer> => {
  const response = await api.post<RagAnswer>('/info/ask', { query, top_k });
  return response.data;
};

export default api;
