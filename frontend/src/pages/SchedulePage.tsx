import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getInfoList } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';

// SOT-1306: 日付つきの予定（event_date あり）を月カレンダーで可視化し、
// カレンダーの下に予定一覧を表示する。該当日はカレンダー上で強調表示する。

const pad = (n: number): string => String(n).padStart(2, '0');

// ローカル日付コンポーネントから YYYY-MM-DD を生成（UTC 変換によるズレを避ける）。
const fmtDate = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

const WEEKDAY_LABELS: Record<'ja' | 'en', string[]> = {
  ja: ['日', '月', '火', '水', '木', '金', '土'],
  en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
};

const SchedulePage: React.FC = () => {
  const { t, lang } = useI18n();
  const { data, isLoading } = useQuery({
    queryKey: ['info', 'all'],
    queryFn: () => getInfoList({ include_attachments: false }),
  });

  const today = new Date();
  const [viewYear, setViewYear] = useState<number>(today.getFullYear());
  const [viewMonth, setViewMonth] = useState<number>(today.getMonth()); // 0-11
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  // SOT-1307: 一覧の表示を「すべて」/「対応済みのみ」で切り替える。
  const [statusFilter, setStatusFilter] = useState<'all' | 'done'>('all');

  // 日付つきの予定のみを対象にする。
  const events = useMemo<NurseryInfo[]>(
    () => (data ?? []).filter((item) => Boolean(item.event_date)),
    [data],
  );

  // 日付ごとの予定件数（カレンダー強調用）。
  const countByDate = useMemo<Record<string, number>>(() => {
    const map: Record<string, number> = {};
    for (const ev of events) {
      const key = ev.event_date as string;
      map[key] = (map[key] ?? 0) + 1;
    }
    return map;
  }, [events]);

  // カレンダーグリッド（日曜始まり、前後月の埋めセルを含む）。
  const weeks = useMemo<Date[][]>(() => {
    const first = new Date(viewYear, viewMonth, 1);
    const start = new Date(first);
    start.setDate(first.getDate() - first.getDay()); // 直前の日曜まで戻す
    const cells: Date[] = [];
    const cursor = new Date(start);
    // 6週（42セル）固定で月をカバーする。
    for (let i = 0; i < 42; i += 1) {
      cells.push(new Date(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    const rows: Date[][] = [];
    for (let i = 0; i < cells.length; i += 7) {
      rows.push(cells.slice(i, i + 7));
    }
    return rows;
  }, [viewYear, viewMonth]);

  // 一覧（既定: 日付つき予定をすべて日付昇順。カレンダーで日付選択時はその日のみ。
  // ステータスフィルタが 'done' のときは「対応済み」のみ）。
  const listItems = useMemo<NurseryInfo[]>(() => {
    let filtered = selectedDate
      ? events.filter((ev) => ev.event_date === selectedDate)
      : events;
    if (statusFilter === 'done') {
      filtered = filtered.filter((ev) => ev.status === '対応済み');
    }
    return [...filtered].sort((a, b) => (a.event_date as string).localeCompare(b.event_date as string));
  }, [events, selectedDate, statusFilter]);

  const todayStr = fmtDate(today);

  const goPrevMonth = () => {
    setSelectedDate(null);
    if (viewMonth === 0) {
      setViewYear((y) => y - 1);
      setViewMonth(11);
    } else {
      setViewMonth((m) => m - 1);
    }
  };
  const goNextMonth = () => {
    setSelectedDate(null);
    if (viewMonth === 11) {
      setViewYear((y) => y + 1);
      setViewMonth(0);
    } else {
      setViewMonth((m) => m + 1);
    }
  };

  const monthTitle = new Intl.DateTimeFormat(lang === 'ja' ? 'ja-JP' : 'en-US', {
    year: 'numeric',
    month: 'long',
  }).format(new Date(viewYear, viewMonth, 1));

  return (
    <div className="w-full lg:max-w-4xl lg:mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-foreground">{t('schedule.title')}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t('schedule.subtitle')}</p>

      {/* カレンダー */}
      <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6">
        <div className="flex items-center justify-between px-4 py-3 bg-brand/10 text-foreground font-bold">
          <button
            type="button"
            onClick={goPrevMonth}
            aria-label={t('schedule.prevMonth')}
            className="px-3 py-1 rounded-lg hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
          >
            ‹
          </button>
          <span>{monthTitle}</span>
          <button
            type="button"
            onClick={goNextMonth}
            aria-label={t('schedule.nextMonth')}
            className="px-3 py-1 rounded-lg hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
          >
            ›
          </button>
        </div>
        <div className="p-3">
          <div className="grid grid-cols-7 gap-1 mb-1">
            {WEEKDAY_LABELS[lang].map((w) => (
              <div key={w} className="text-center text-xs font-semibold text-muted-foreground py-1">
                {w}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {weeks.flat().map((d) => {
              const dateStr = fmtDate(d);
              const inMonth = d.getMonth() === viewMonth;
              const count = countByDate[dateStr] ?? 0;
              const hasEvent = count > 0;
              const isToday = dateStr === todayStr;
              const isSelected = dateStr === selectedDate;

              const base =
                'relative aspect-square rounded-lg flex flex-col items-center justify-center text-sm transition-colors';
              const tone = inMonth ? 'text-foreground' : 'text-muted-foreground/50';
              let cls = `${base} ${tone}`;
              if (isSelected) {
                cls += ' bg-brand text-white font-bold';
              } else if (hasEvent) {
                cls += ' bg-brand/15 font-semibold hover:bg-brand/25 cursor-pointer';
              } else {
                cls += ' hover:bg-surface-muted';
              }
              if (isToday && !isSelected) {
                cls += ' ring-2 ring-brand/50';
              }

              if (hasEvent) {
                return (
                  <button
                    key={dateStr}
                    type="button"
                    onClick={() => setSelectedDate(isSelected ? null : dateStr)}
                    className={cls}
                    aria-pressed={isSelected}
                    aria-label={`${dateStr} (${count})`}
                  >
                    <span>{d.getDate()}</span>
                    <span
                      aria-hidden
                      className={`mt-0.5 h-1.5 w-1.5 rounded-full ${isSelected ? 'bg-white' : 'bg-brand'}`}
                    />
                  </button>
                );
              }
              return (
                <div key={dateStr} className={cls}>
                  <span>{d.getDate()}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* カレンダーの下の予定一覧 */}
      <div className="bg-surface rounded-2xl shadow-card overflow-hidden mb-6">
        <div className="flex items-center gap-2 px-4 py-3 bg-emerald-50 text-emerald-700 font-bold">
          <span aria-hidden className="text-lg">📅</span>
          <span>{t('schedule.listTitle')}</span>
          {selectedDate && (
            <button
              type="button"
              onClick={() => setSelectedDate(null)}
              className="ml-auto text-xs font-normal text-emerald-700 underline hover:no-underline focus:outline-none focus:ring-2 focus:ring-brand/40 rounded"
            >
              {t('schedule.clearFilter')}
            </button>
          )}
        </div>
        {/* SOT-1307: 「すべて / 対応済み」表示切替 */}
        <div className="flex gap-2 px-4 pt-3" role="group" aria-label={t('schedule.listTitle')}>
          {(['all', 'done'] as const).map((key) => {
            const active = statusFilter === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setStatusFilter(key)}
                aria-pressed={active}
                className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-colors focus:outline-none focus:ring-2 focus:ring-brand/40 ${
                  active
                    ? 'bg-brand text-white border-brand'
                    : 'bg-surface text-foreground border-border hover:bg-surface-muted'
                }`}
              >
                {key === 'all' ? t('schedule.showAll') : t('schedule.showDone')}
              </button>
            );
          })}
        </div>
        <div className="p-4">
          {selectedDate && (
            <p className="text-xs text-muted-foreground mb-2">
              {t('schedule.filteredBy')}
              {selectedDate}
            </p>
          )}
          {isLoading ? (
            <p className="text-muted-foreground">{t('common.loading')}</p>
          ) : listItems.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t('common.noData')}</p>
          ) : (
            <ul className="divide-y divide-border">
              {listItems.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/data/${item.id}`}
                    className="block py-2 -mx-2 px-2 rounded-lg transition-colors hover:bg-surface-muted focus:outline-none focus:ring-2 focus:ring-brand/40"
                  >
                    <div className="flex justify-between items-center gap-3">
                      <span className="font-medium text-foreground truncate">{item.title}</span>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className="text-xs bg-emerald-100 text-emerald-800 px-2 py-1 rounded-full">
                          {item.event_date}
                        </span>
                        <span className="text-xs text-muted-foreground">{item.info_type}</span>
                      </div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};

export default SchedulePage;
