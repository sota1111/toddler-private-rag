import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getInfoList, createInfo } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import DatedInfoList from '../components/DatedInfoList';
import { INFO_TYPES, STATUS_TYPES } from './infoFormOptions';

// SOT-1313: カレンダー画面（SchedulePage）の「カレンダーの下の予定一覧」と同じ内容を、
// 独立した「タスク一覧」メニューとして表示する。各項目クリックで既存の詳細 /data/:id へ遷移する。
// SOT-1342: 予定一覧との重複する一覧部分（ステータス絞り込み + 行リスト）を共有コンポーネント
// DatedInfoList に1箇所化（タスク一覧が正）。
// SOT-1358: タスクを手動で追加するボタン + 入力フォームを追加。既存の createInfo API を再利用し、
// 追加後は ['info','all'] クエリを invalidate して一覧へ即時反映する。

const TasksPage: React.FC = () => {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['info', 'all'],
    queryFn: () => getInfoList({ include_attachments: false }),
  });

  // 種別/ステータスの選択肢ラベル（保存値は日本語のまま、表示は設定言語に翻訳）。
  const optLabel = (group: string, value: string) => {
    const key = `options.${group}.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  // 手動追加フォームの状態。
  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [eventDate, setEventDate] = useState('');
  const [infoType, setInfoType] = useState(INFO_TYPES[0]);
  const [status, setStatus] = useState(STATUS_TYPES[0]);
  const [content, setContent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // 日付つきの予定のみを対象にする。
  const events = useMemo<NurseryInfo[]>(
    () => (data ?? []).filter((item) => Boolean(item.event_date)),
    [data],
  );

  const resetForm = () => {
    setTitle('');
    setEventDate('');
    setInfoType(INFO_TYPES[0]);
    setStatus(STATUS_TYPES[0]);
    setContent('');
    setSubmitError(null);
  };

  const closeForm = () => {
    setFormOpen(false);
    resetForm();
  };

  // 一覧表示の条件（event_date あり）に合わせ、タイトルと日付は必須にする。
  const canSubmit = title.trim().length > 0 && eventDate.length > 0 && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createInfo({
        title: title.trim(),
        info_type: infoType,
        content: content,
        event_date: eventDate,
        status,
        priority: '普通',
      });
      await queryClient.invalidateQueries({ queryKey: ['info', 'all'] });
      closeForm();
    } catch {
      setSubmitError(t('tasks.submitError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto">
      <div className="flex items-start justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold mb-1 text-foreground">{t('tasks.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('tasks.subtitle')}</p>
        </div>
        {!formOpen && (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="shrink-0 rounded-xl bg-brand px-4 py-2 text-sm font-bold text-white shadow-card hover:bg-brand-strong"
          >
            ＋ {t('tasks.addButton')}
          </button>
        )}
      </div>

      {formOpen && (
        <form
          onSubmit={handleSubmit}
          className="bg-surface rounded-2xl shadow-card p-4 mb-6 space-y-3"
        >
          <h2 className="text-lg font-bold text-foreground">{t('tasks.formTitle')}</h2>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-foreground">{t('tasks.fieldTitle')}</span>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground"
              required
            />
          </label>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-foreground">{t('tasks.fieldDate')}</span>
            <input
              type="date"
              value={eventDate}
              onChange={(e) => setEventDate(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground"
              required
            />
          </label>

          <div className="flex gap-3">
            <label className="block flex-1 text-sm">
              <span className="mb-1 block font-medium text-foreground">{t('tasks.fieldType')}</span>
              <select
                value={infoType}
                onChange={(e) => setInfoType(e.target.value)}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground"
              >
                {INFO_TYPES.map((v) => (
                  <option key={v} value={v}>{optLabel('infoType', v)}</option>
                ))}
              </select>
            </label>

            <label className="block flex-1 text-sm">
              <span className="mb-1 block font-medium text-foreground">{t('tasks.fieldStatus')}</span>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground"
              >
                {STATUS_TYPES.map((s) => (
                  <option key={s} value={s}>{optLabel('status', s)}</option>
                ))}
              </select>
            </label>
          </div>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-foreground">{t('tasks.fieldContent')}</span>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground"
            />
          </label>

          {submitError && <p className="text-sm text-red-600">{submitError}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={closeForm}
              className="rounded-xl px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-surface-muted"
            >
              {t('tasks.cancel')}
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-xl bg-brand px-4 py-2 text-sm font-bold text-white shadow-card hover:bg-brand-strong disabled:opacity-50"
            >
              {t('tasks.submit')}
            </button>
          </div>
        </form>
      )}

      <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6">
        <div className="flex items-center gap-2 px-4 py-3 bg-emerald-50 text-emerald-700 font-bold">
          <span aria-hidden className="text-lg">📅</span>
          <span>{t('tasks.listTitle')}</span>
        </div>
        <DatedInfoList items={events} isLoading={isLoading} namespace="tasks" />
      </div>
    </div>
  );
};

export default TasksPage;
