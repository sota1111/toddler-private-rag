import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getInfoList, getAttachmentFileUrl } from '../api';

const INFO_TYPES = ["すべて", "資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"];
const STATUS_TYPES = ["すべて", "未対応", "対応済み", "確認済み"];

const InfoListPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [infoType, setInfoType] = useState('すべて');
  const [status, setStatus] = useState('すべて');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data: items, isLoading } = useQuery({
    queryKey: ['info', query, infoType, status],
    queryFn: () => getInfoList({
      q: query || undefined,
      info_type: infoType === 'すべて' ? undefined : infoType,
      status: status === 'すべて' ? undefined : status,
    }),
  });

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case '高': return 'text-red-600 bg-red-50';
      case '普通': return 'text-blue-600 bg-blue-50';
      case '低': return 'text-gray-600 bg-gray-50';
      default: return 'text-gray-600 bg-gray-50';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case '未対応': return 'bg-yellow-100 text-yellow-800';
      case '対応済み': return 'bg-green-100 text-green-800';
      case '確認済み': return 'bg-blue-100 text-blue-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 pb-12">
      <h1 className="text-2xl font-bold mb-6 text-gray-800">情報一覧</h1>

      <div className="bg-white p-4 rounded-lg shadow-sm mb-6 grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">キーワード検索</label>
          <input
            type="text"
            className="w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm p-2 border"
            placeholder="タイトルや内容..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">種別</label>
          <select
            className="w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm p-2 border"
            value={infoType}
            onChange={(e) => setInfoType(e.target.value)}
          >
            {INFO_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">ステータス</label>
          <select
            className="w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm p-2 border"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {STATUS_TYPES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-10 text-gray-500">読み込み中...</div>
      ) : !items || items.length === 0 ? (
        <div className="text-center py-10 text-gray-400">該当する情報がありません。</div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <div 
              key={item.id} 
              className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden cursor-pointer hover:border-blue-300 transition-colors"
              onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
            >
              <div className="p-4 sm:flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center space-x-2 mb-1">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                      {item.info_type}
                    </span>
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getPriorityColor(item.priority)}`}>
                      {item.priority}
                    </span>
                    {item.attachments && item.attachments.length > 0 && (
                      <span className="inline-flex items-center text-xs text-gray-500">
                        <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path>
                        </svg>
                        {item.attachments.length}
                      </span>
                    )}
                  </div>
                  <h3 className="text-lg font-bold text-gray-900">{item.title}</h3>
                  <div className="mt-1 text-sm text-gray-500 space-x-4">
                    {item.date && <span>日付: {item.date}</span>}
                    {item.due_date && <span className="text-red-500 font-semibold">期限: {item.due_date}</span>}
                  </div>
                </div>
                <div className="mt-2 sm:mt-0 flex items-center space-x-2">
                  <span className={`px-3 py-1 rounded-full text-sm font-bold ${getStatusColor(item.status)}`}>
                    {item.status}
                  </span>
                  <div className="text-gray-400">
                    {expandedId === item.id ? '▲' : '▼'}
                  </div>
                </div>
              </div>
              
              {expandedId === item.id && (
                <div className="px-4 pb-4 border-t border-gray-100 bg-gray-50 pt-4 animate-fadeIn">
                  <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap break-words">
                    {item.content}
                  </div>
                  {item.items && (
                    <div className="mt-4 p-2 bg-blue-50 rounded border border-blue-100">
                      <p className="text-xs font-bold text-blue-800 uppercase tracking-wider mb-1">持ち物</p>
                      <p className="text-sm text-blue-900 break-words">{item.items}</p>
                    </div>
                  )}
                  {item.memo && (
                    <div className="mt-4">
                      <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">メモ</p>
                      <p className="text-sm text-gray-600 italic break-words">{item.memo}</p>
                    </div>
                  )}
                  {item.attachments && item.attachments.length > 0 && (
                    <div className="mt-4">
                      <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">添付ファイル</p>
                      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
                        {item.attachments.map((att) => (
                          <div key={att.id} className="relative group" onClick={(e) => e.stopPropagation()}>
                            {att.mime_type.startsWith('image/') ? (
                              <div className="aspect-square bg-gray-200 rounded-md overflow-hidden border border-gray-300">
                                <img 
                                  src={getAttachmentFileUrl(att.id)} 
                                  alt={att.original_filename}
                                  className="w-full h-full object-cover cursor-pointer hover:opacity-90 transition-opacity"
                                  loading="lazy"
                                  onClick={() => window.open(getAttachmentFileUrl(att.id), '_blank')}
                                />
                              </div>
                            ) : (
                              <a 
                                href={getAttachmentFileUrl(att.id)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="aspect-square flex flex-col items-center justify-center bg-white rounded-md border border-gray-300 p-2 hover:bg-gray-50 transition-colors"
                              >
                                <svg className="w-8 h-8 text-gray-400 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                                </svg>
                                <span className="text-[10px] text-gray-600 text-center line-clamp-2 break-all px-1">
                                  {att.original_filename}
                                </span>
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {item.tags && (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {item.tags.split(',').map(tag => (
                        <span key={tag} className="text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded">#{tag.trim()}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default InfoListPage;
