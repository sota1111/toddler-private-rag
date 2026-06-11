import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createInfo } from '../api';
import type { NurseryInfoCreate } from '../types';

const INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"];
const STATUS_TYPES = ["未対応", "対応済み", "確認済み"];
const PRIORITY_TYPES = ["高", "普通", "低"];

const InfoCreatePage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState<NurseryInfoCreate>({
    title: '',
    info_type: '資料',
    content: '',
    date: '',
    event_date: '',
    due_date: '',
    items: '',
    status: '未対応',
    priority: '普通',
    tags: '',
    memo: '',
  });

  const mutation = useMutation({
    mutationFn: createInfo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['info'] });
      queryClient.invalidateQueries({ queryKey: ['tomorrow'] });
      queryClient.invalidateQueries({ queryKey: ['weekly'] });
      queryClient.invalidateQueries({ queryKey: ['pending'] });
      navigate('/list');
    },
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate(formData);
  };

  return (
    <div className="max-w-3xl mx-auto px-4">
      <h1 className="text-2xl font-bold mb-6 text-gray-800">情報登録</h1>
      
      <form onSubmit={handleSubmit} className="bg-white shadow-md rounded-lg p-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700">タイトル *</label>
            <input
              type="text"
              name="title"
              required
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.title}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">種別 *</label>
            <select
              name="info_type"
              required
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.info_type}
              onChange={handleChange}
            >
              {INFO_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">ステータス</label>
            <select
              name="status"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.status}
              onChange={handleChange}
            >
              {STATUS_TYPES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">優先度</label>
            <select
              name="priority"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.priority}
              onChange={handleChange}
            >
              {PRIORITY_TYPES.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">日付</label>
            <input
              type="date"
              name="date"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.date}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">行事日</label>
            <input
              type="date"
              name="event_date"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.event_date}
              onChange={handleChange}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">提出期限</label>
            <input
              type="date"
              name="due_date"
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
              value={formData.due_date}
              onChange={handleChange}
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">内容 *</label>
          <textarea
            name="content"
            required
            rows={4}
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            value={formData.content}
            onChange={handleChange}
          ></textarea>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">持ち物</label>
          <input
            type="text"
            name="items"
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            placeholder="お弁当, 水筒, ..."
            value={formData.items}
            onChange={handleChange}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">タグ (カンマ区切り)</label>
          <input
            type="text"
            name="tags"
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            placeholder="遠足, 重要, ..."
            value={formData.tags}
            onChange={handleChange}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">メモ</label>
          <textarea
            name="memo"
            rows={2}
            className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2"
            value={formData.memo}
            onChange={handleChange}
          ></textarea>
        </div>

        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="mr-4 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            キャンセル
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-6 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-blue-300"
          >
            {mutation.isPending ? '登録中...' : '登録する'}
          </button>
        </div>
        
        {mutation.isError && (
          <p className="mt-2 text-sm text-red-600 text-center">エラーが発生しました。もう一度お試しください。</p>
        )}
      </form>
    </div>
  );
};

export default InfoCreatePage;
