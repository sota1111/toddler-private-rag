import axios from 'axios';
import type {
  Child,
  NurseryInfo,
  NurseryInfoCreate,
  Attachment,
  UploadSession,
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

// アーカイブ済み一覧取得 (SOT-1500)。is_archived=true の本登録項目のみを返す。
export const getArchivedList = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/archived');
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

// 子供 (SOT-1368: option A, 1家族で複数の子供)
export const getChildren = async (): Promise<Child[]> => {
  const response = await api.get('/children');
  return response.data;
};

export const createChild = async (name: string): Promise<Child> => {
  const response = await api.post('/children', { name });
  return response.data;
};

export const deleteChild = async (id: number | string): Promise<void> => {
  await api.delete(`/children/${id}`);
};

// 既存の仮登録(draft)を部分更新する (SOT-1175: 写真アップ後の best-effort 補完用)
// SOT-1468: 写真詳細画面から登録月(created_at)を変更できるよう、更新ペイロードに created_at を許可する。
export const updateInfo = async (id: number | string, data: Partial<NurseryInfoCreate> & { created_at?: string }): Promise<NurseryInfo> => {
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

// 文字起こし中(processing)の件数 (SOT-1380)。仮登録画面のインジケータ用。
export const getProcessingCount = async (): Promise<number> => {
  const response = await api.get('/info/drafts/processing-count');
  return response.data?.count ?? 0;
};

// 文字起こし(読み取り)中の項目一覧 (SOT-1499)。仮登録画面に「読み取り中」カードとして表示する。
export const getProcessingDrafts = async (): Promise<NurseryInfo[]> => {
  const response = await api.get('/info/drafts/processing');
  return response.data;
};

// 仮登録を本登録(registered)に確定する (SOT-1113)
export const finalizeInfo = async (id: number | string): Promise<NurseryInfo> => {
  const response = await api.post(`/info/${id}/finalize`);
  return response.data;
};

// 締め切り調査 (SOT-1369): 選択した項目に対し提出書類先回りエージェントを手動起動し、
// 提出準備タスク(draft)を生成する。
// SOT-1405: 設定の市町村を渡し、市区町村窓口/公式HPから様式をDLする手順に
// ダウンロードページリンクを付与できるようにする。
export const investigateDeadline = async (
  id: number | string,
  municipality?: string,
): Promise<{ created: number; ids: (number | string)[] }> => {
  const response = await api.post(`/info/${id}/investigate-deadline`, {
    municipality: municipality ?? '',
  });
  return response.data;
};

// SOT-1411: 締切調査タスクの基準日(最終提出期限)を変更し、同じ締切調査グループの付随タスクを
// 保存済みオフセットでまとめてずらす。
export const rescheduleDeadline = async (
  id: number | string,
  baseDate: string,
): Promise<{ updated: number; ids: (number | string)[] }> => {
  const response = await api.post(`/info/${id}/reschedule-deadline`, {
    base_date: baseDate,
  });
  return response.data;
};

export const uploadAttachment = async (
  infoId: number | string,
  file: File,
  // SOT-1315: 文字起こし後のタスク登録を、この言語で生成させる（未指定時はサーバ側が ja 既定）。
  language?: string,
  // SOT-1405: 設定済み市町村。自動締切調査で市町村ダウンロードリンクを付与するために送る。
  municipality?: string,
): Promise<Attachment> => {
  const formData = new FormData();
  formData.append('file', file);
  const params = new URLSearchParams();
  if (language) params.set('language', language);
  if (municipality) params.set('municipality', municipality);
  const qs = params.toString();
  const url = qs
    ? `/info/${infoId}/attachments?${qs}`
    : `/info/${infoId}/attachments`;
  const response = await api.post<Attachment>(url, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

// SOT-1377: GCS direct upload。session を発行し、画像本体は Cloud Run を経由せず
// ブラウザから GCS へ直接 PUT する。OCR は GCS finalize イベント経由で非同期起動する。
export const createUploadSession = async (
  infoId: number | string,
  file: File,
  language?: string,
  municipality?: string,
): Promise<UploadSession> => {
  const response = await api.post<UploadSession>(`/info/${infoId}/upload/session`, {
    filename: file.name,
    content_type: file.type,
    file_size: file.size,
    language: language || 'ja',
    // SOT-1405: 自動締切調査の市町村ダウンロードリンク付与に使う。
    municipality: municipality || '',
  });
  return response.data;
};

// session の署名付き URL に画像本体を直接 PUT する。api(axios, baseURL=/api, credentials)
// ではなく素の fetch を使う（署名 URL は GCS の絶対 URL で、Cookie/baseURL を付けない）。
const putFileToSignedUrl = async (session: UploadSession, file: File): Promise<void> => {
  const headers: Record<string, string> = { ...(session.required_headers || {}) };
  if (!headers['Content-Type'] && file.type) headers['Content-Type'] = file.type;
  const res = await fetch(session.upload_url, {
    method: session.method || 'PUT',
    headers,
    body: file,
  });
  if (!res.ok) {
    throw new Error(`Direct upload failed: ${res.status}`);
  }
};

// SOT-1378: GCS 直 PUT 完了後、finalize を明示的に呼んで OCR を起動する。
// GCS OBJECT_FINALIZE→Pub/Sub 通知に依存させない（冪等なので二重起動でも安全）。
// これを呼ばないと、画像は GCS に保存されても仮登録・写真一覧に反映されない。
export const finalizeUploadSession = async (
  infoId: number | string,
  uploadId: number | string,
): Promise<void> => {
  await api.post(`/info/${infoId}/upload/session/${uploadId}/finalize`);
};

// 2段アップロード。session 発行に失敗（未対応 501 等）したときだけ従来の multipart に
// フォールバックする。session 取得後の PUT 失敗はそのまま投げる（二重アップロード防止）。
export const uploadAttachmentSmart = async (
  infoId: number | string,
  file: File,
  language?: string,
  municipality?: string,
): Promise<void> => {
  let session: UploadSession | null;
  try {
    session = await createUploadSession(infoId, file, language, municipality);
  } catch {
    session = null;
  }
  // session 未対応（501 / エラー / 署名URLを返さない）の場合は従来の multipart に
  // フォールバックする（multipart 側は同期 OCR なので finalize 不要）。
  // upload_url が得られたときだけ GCS へ直接 PUT する。
  if (!session || !session.upload_url) {
    await uploadAttachment(infoId, file, language, municipality);
    return;
  }
  await putFileToSignedUrl(session, file);
  // SOT-1378 follow-up: 画像本体を GCS へ PUT し終えた時点で「アップロード完了」(写真は保存済み)。
  // ここで finalize の応答を await すると、「アップ中」表示が文字起こし・タスク登録の完了まで
  // 継続してしまう（SOT-1322 の「保存完了＝即 done」不変条件の退行）。finalize は OCR を起動する
  // ためのトリガーであり、リクエストが backend に届けば OCR は background task として起動するので、
  // レスポンスを await する必要はない。万一 finalize が届かなくても GCS finalize(Pub/Sub) が backup
  // として OCR を起動する（二重起動は begin_ocr_if_pending の CAS で冪等に吸収される）。
  void finalizeUploadSession(infoId, session.upload_id).catch((e) => {
    console.warn('finalizeUploadSession failed (OCR will still be triggered via GCS finalize)', e);
  });
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

// SOT-1473: 回答へのフィードバック（👍/👎）を送る。精度改善の一次データ収集用。
export const sendAnswerFeedback = async (
  question: string,
  answer: string,
  rating: 'up' | 'down',
): Promise<void> => {
  await api.post('/feedback', { question, answer, rating });
};

// SOT-1374 / C: ストリーミング版の質問。回答トークンを逐次受け取り、体感待ち時間を縮める。
// SSE(text/event-stream)を fetch で読み、token を onToken に流す。非対応環境では呼び出し側が
// askInfo(/info/ask) にフォールバックできるよう、失敗時は例外を投げる。
export const askInfoStream = async (
  query: string,
  handlers: { onToken?: (text: string) => void; onSources?: (sources: RagAnswer['sources']) => void },
  top_k = 4,
): Promise<RagAnswer> => {
  const response = await fetch('/api/info/ask-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ query, top_k }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`ask-stream failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let answer = '';
  let sources: RagAnswer['sources'] = [];

  const handleEvent = (event: string, data: string) => {
    if (event === 'sources') {
      try {
        sources = JSON.parse(data);
        handlers.onSources?.(sources);
      } catch {
        /* ignore malformed sources frame */
      }
    } else if (event === 'token') {
      try {
        const text = JSON.parse(data).text ?? '';
        answer += text;
        if (text) handlers.onToken?.(text);
      } catch {
        /* ignore malformed token frame */
      }
    }
  };

  // SSE フレームは空行(\n\n)区切り。各フレームの "event:" と "data:" 行をパースする。
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length) handleEvent(event, dataLines.join('\n'));
    }
  }

  return { answer, sources };
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
