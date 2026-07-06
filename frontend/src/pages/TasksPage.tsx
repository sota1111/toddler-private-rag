import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getInfoList, createInfo, getChildren } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import DatedInfoList from '../components/DatedInfoList';
import { INFO_TYPES, STATUS_TYPES } from './infoFormOptions';

// SOT-1313: カレンダー画面（SchedulePage）の「カレンダーの下の予定一覧」と同じ内容を、
// 独立した「タスク一覧」メニューとして表示する。各項目クリックで既存の詳細 /data/:id へ遷移する。
// SOT-1342: 予定一覧との重複する一覧部分（ステータス絞り込み + 行リスト）を共有コンポーネント
// DatedInfoList に1箇所化（タスク一覧が正）。
// SOT-1358: タスクを手動で追加するボタン + 入力フォームを追加。既存の createInfo API を再利用し、
// 追加後は ['info'] クエリを invalidate して一覧へ即時反映する。
// SOT-1408: 写真をアップロードすると「写真本体のレコード（添付あり・予定日なし＝登録一覧用）」と
// 「文字起こしから分解したタスク」が別レコードで作られる（SOT-1318）。やることリストには分解した
// タスクだけを出し、写真本体は登録一覧(RegisteredListPage)にのみ出す。RegisteredListPage と同じく
// 「添付を持つレコード＝写真本体」と判定し、その逆（添付なし）だけをやることリストに表示する。
// そのため添付情報が必要なので、SchedulePage が使う ['info','all']+include_attachments:false とは
// 別のクエリキーで添付付き取得する。

const TasksPage: React.FC = () => {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['info', 'tasks'],
    queryFn: () => getInfoList(),
  });
  // SOT-1368: 紐づけるお子さまの選択肢。
  const { data: children } = useQuery({
    queryKey: ['children'],
    queryFn: getChildren,
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
  const [childId, setChildId] = useState('');
  const [content, setContent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // SOT-1365: 日付不明（event_date 無し）のタスクも「期限なし」として表示するため、
  // 日付ありの絞り込みを外して全件を一覧へ渡す（カレンダーページは別途 event_date ありのみ表示）。
  // SOT-1408: ただし写真本体のレコード（添付を持つ＝登録一覧用）はやることリストから除外する。
  // 分解されたタスクや手動追加タスクは添付を持たないため残り、写真は登録一覧にのみ表示される。
  const events = useMemo<NurseryInfo[]>(
    () => (data ?? []).filter((it) => (it.attachments?.length ?? 0) === 0),
    [data],
  );

  const resetForm = () => {
    setTitle('');
    setEventDate('');
    setInfoType(INFO_TYPES[0]);
    setStatus(STATUS_TYPES[0]);
    setChildId('');
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
        child_id: childId || null,
      });
      // SOT-1408: ['info'] プレフィックスを invalidate し、やることリスト(['info','tasks'])と
      // カレンダー(['info','all']) の両方を即時更新する。
      await queryClient.invalidateQueries({ queryKey: ['info'] });
      closeForm();
    } catch {
      setSubmitError(t('tasks.submitError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto">
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

          {children && children.length > 0 && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-foreground">{t('child.fieldLabel')}</span>
              <select
                value={childId}
                onChange={(e) => setChildId(e.target.value)}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground"
              >
                <option value="">{t('child.none')}</option>
                {children.map((c) => (
                  <option key={c.id} value={String(c.id)}>{c.name}</option>
                ))}
              </select>
            </label>
          )}

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

      <div className="bg-surface rounded-2xl shadow-card border border-border overflow-hidden mb-6">
        <div className="flex items-center justify-between gap-2 px-4 py-3 bg-accent-bg text-brand-strong font-bold border-b border-accent-border">
          <div className="flex items-center gap-2">
            <span aria-hidden className="text-lg">📅</span>
            <span>{t('tasks.listTitle')}</span>
          </div>
          {!formOpen && (
            <button
              type="button"
              onClick={() => setFormOpen(true)}
              className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white shadow-card hover:bg-brand-strong"
            >
              ＋ {t('tasks.addButton')}
            </button>
          )}
        </div>
        {/* SOT-1557: やることリストではカテゴリ（種別）表示を非表示にする。 */}
        <DatedInfoList
          items={events}
          isLoading={isLoading}
          namespace="tasks"
          groupByMonth
          showCategory={false}
        />
      </div>
    </div>
  );
};

export default TasksPage;
