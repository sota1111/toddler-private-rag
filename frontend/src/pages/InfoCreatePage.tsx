import React, { useState, useRef } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createInfo, uploadAttachment } from '../api';
import type { NurseryInfoCreate } from '../types';

const INFO_TYPES = ["資料", "掲示", "行事", "持ち物", "提出物", "お知らせ", "給食", "休園変更"];
const STATUS_TYPES = ["未対応", "対応済み", "確認済み"];
const PRIORITY_TYPES = ["高", "普通", "低"];

const InfoCreatePage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
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

  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState({ current: 0, total: 0 });
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: createInfo,
    onSuccess: async (newInfo) => {
      if (selectedFiles.length > 0) {
        setIsUploading(true);
        setUploadProgress({ current: 0, total: selectedFiles.length });
        
        const failedFiles: string[] = [];
        
        for (let i = 0; i < selectedFiles.length; i++) {
          setUploadProgress({ current: i + 1, total: selectedFiles.length });
          try {
            await uploadAttachment(newInfo.id, selectedFiles[i]);
          } catch (error: unknown) {
            console.error(`Failed to upload ${selectedFiles[i].name}`, error);
            let msg = selectedFiles[i].name;
            if (axios.isAxiosError(error)) {
              if (error.response?.status === 413) {
                msg += " (ファイルサイズが大きすぎます)";
              } else if (error.response?.status === 400) {
                msg += " (サポートされていない形式です)";
              } else {
                msg += " (エラーが発生しました)";
              }
            } else {
              msg += " (エラーが発生しました)";
            }
            failedFiles.push(msg);
          }
        }
        
        setIsUploading(false);
        
        if (failedFiles.length > 0) {
          setErrorMessage(`一部のファイルのアップロードに失敗しました:\n${failedFiles.join('\n')}`);
          // Stay on page if there's an error so user can see it
          queryClient.invalidateQueries({ queryKey: ['info'] });
          return;
        }
      }

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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    mutation.mutate(formData);
  };

  const isSubmitting = mutation.isPending || isUploading;

  return (
    <div className="max-w-3xl mx-auto px-4 pb-12">
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
              disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
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
            disabled={isSubmitting}
          ></textarea>
        </div>

        <div className="border-t border-gray-200 pt-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">添付ファイル (画像またはPDF)</label>
          <input
            type="file"
            multiple
            accept="image/*,application/pdf"
            onChange={handleFileChange}
            ref={fileInputRef}
            className="block w-full text-sm text-gray-500
              file:mr-4 file:py-2 file:px-4
              file:rounded-md file:border-0
              file:text-sm file:font-semibold
              file:bg-blue-50 file:text-blue-700
              hover:file:bg-blue-100"
            disabled={isSubmitting}
          />
          {selectedFiles.length > 0 && (
            <ul className="mt-2 text-sm text-gray-600 space-y-1">
              {selectedFiles.map((file, i) => (
                <li key={i} className="flex items-center">
                  <span className="truncate max-w-xs">{file.name}</span>
                  <span className="ml-2 text-gray-400">({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
                </li>
              ))}
            </ul>
          )}
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
            disabled={isSubmitting}
            className="px-6 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:bg-blue-300 min-w-[120px]"
          >
            {mutation.isPending ? '登録中...' : 
             isUploading ? `アップロード中 (${uploadProgress.current}/${uploadProgress.total})` : 
             '登録する'}
          </button>
        </div>
        
        {errorMessage && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-600 whitespace-pre-wrap">{errorMessage}</p>
            {!isUploading && (
               <button 
                type="button"
                onClick={() => navigate('/list')}
                className="mt-2 text-sm text-blue-600 font-medium hover:underline"
              >
                一覧へ戻る
              </button>
            )}
          </div>
        )}
        
        {mutation.isError && !errorMessage && (
          <p className="mt-2 text-sm text-red-600 text-center">エラーが発生しました。もう一度お試しください。</p>
        )}
      </form>
    </div>
  );
};

export default InfoCreatePage;
