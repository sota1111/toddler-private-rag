import React, { useState } from 'react';
import { askInfo } from '../api';
import type { RagAnswer } from '../types';

const AskPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<RagAnswer | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q || isLoading) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await askInfo(q);
      setResult(data);
    } catch {
      setError('回答の取得に失敗しました。時間をおいて再度お試しください。');
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 pb-12">
      <h1 className="text-2xl font-bold mb-6 text-gray-800">質問する</h1>

      <form onSubmit={handleSubmit} className="bg-white p-4 rounded-lg shadow-sm mb-6">
        <label htmlFor="ask-query" className="block text-sm font-medium text-gray-700 mb-1">
          保育園の情報について質問してください
        </label>
        <textarea
          id="ask-query"
          rows={3}
          className="w-full border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm p-2"
          placeholder="例: 来週の遠足の持ち物は？"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className="px-4 py-2 rounded-md text-sm font-medium text-white bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? '回答中...' : '送信'}
          </button>
        </div>
      </form>

      {error && (
        <div className="mb-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {error}
        </div>
      )}

      {isLoading && (
        <div className="flex flex-col items-center justify-center py-12 text-gray-500">
          <span className="h-8 w-8 mb-3 rounded-full border-2 border-gray-200 border-t-blue-500 animate-spin" aria-hidden />
          <p className="text-sm">回答を生成しています...</p>
        </div>
      )}

      {!isLoading && !result && !error && (
        <div className="text-center py-12 text-gray-400">
          <div className="text-4xl mb-2" aria-hidden>💬</div>
          <p className="text-sm">登録済みの保育園情報をもとにお答えします。</p>
          <p className="text-xs mt-1">上の入力欄から質問してみましょう。</p>
        </div>
      )}

      {!isLoading && result && (
        <div className="space-y-6">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
            <h2 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-2">回答</h2>
            <p className="text-gray-800 whitespace-pre-wrap leading-relaxed">{result.answer}</p>
          </div>

          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
            <h2 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-3">出典</h2>
            {result.sources.length === 0 ? (
              <p className="text-sm text-gray-400">出典はありません。</p>
            ) : (
              <ul className="space-y-2">
                {result.sources.map((s, i) => (
                  <li
                    key={i}
                    className="flex items-center justify-between gap-3 p-3 rounded-md border border-gray-100 bg-gray-50"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          s.source === 'ocr'
                            ? 'bg-purple-100 text-purple-800'
                            : 'bg-blue-100 text-blue-800'
                        }`}
                      >
                        {s.source === 'ocr' ? '添付' : '本文'}
                      </span>
                      <span className="text-sm text-gray-800 truncate">{s.label || s.title}</span>
                    </div>
                    <span className="text-xs text-gray-500 whitespace-nowrap">
                      関連度 {s.score.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AskPage;
