import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getInfoList } from '../api';

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
    <div className="max-w-5xl mx-auto px-4">
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
                  <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
                    {item.content}
                  </div>
                  {item.items && (
                    <div className="mt-4 p-2 bg-blue-50 rounded border border-blue-100">
                      <p className="text-xs font-bold text-blue-800 uppercase tracking-wider mb-1">持ち物</p>
                      <p className="text-sm text-blue-900">{item.items}</p>
                    </div>
                  )}
                  {item.memo && (
                    <div className="mt-4">
                      <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">メモ</p>
                      <p className="text-sm text-gray-600 italic">{item.memo}</p>
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
