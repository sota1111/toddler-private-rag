import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getInfoList } from '../api';
import type { NurseryInfo } from '../types';
import { useI18n } from '../i18n/useI18n';
import DatedInfoList from '../components/DatedInfoList';

// SOT-1306: 日付つきの予定（event_date あり）を月カレンダーで可視化し、
// カレンダーの下に予定一覧を表示する。該当日はカレンダー上で強調表示する。
// SOT-1342: カレンダー下の予定一覧（ステータス絞り込み + 行リスト）は、タスク一覧と共通の
// 共有コンポーネント DatedInfoList に1箇所化（タスク一覧が正）。カレンダー・選択日フィルタ・
// 見出しバー（ブランド配色）・絞り込み中インジケータは本ページ固有として維持する。

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

  // カレンダーグリッド（日曜始まり、当月先頭週の前月埋めセルは含むが、
  // 当月末日を含む週の次にある「翌月だけの週（翌月の1週目）」は表示しない）。
  const weeks = useMemo<Date[][]>(() => {
    const first = new Date(viewYear, viewMonth, 1);
    const lastDay = new Date(viewYear, viewMonth + 1, 0); // 当月末日
    const start = new Date(first);
    start.setDate(first.getDate() - first.getDay()); // 直前の日曜まで戻す
    const rows: Date[][] = [];
    const cursor = new Date(start);
    // 当月末日を含む週まで生成し、それ以降（翌月だけの週）は出さない。
    while (true) {
      const week: Date[] = [];
      for (let i = 0; i < 7; i += 1) {
        week.push(new Date(cursor));
        cursor.setDate(cursor.getDate() + 1);
      }
      rows.push(week);
      if (week[6] >= lastDay) break; // この週の土曜が当月末日以降になったら終了
    }
    return rows;
  }, [viewYear, viewMonth]);

  // 一覧に渡す項目（カレンダーで日付選択時はその日のみ。ステータス絞り込みとソートは
  // DatedInfoList が担当）。
  const listItems = useMemo<NurseryInfo[]>(
    () => (selectedDate ? events.filter((ev) => ev.event_date === selectedDate) : events),
    [events, selectedDate],
  );

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
    <div className="w-full lg:max-w-6xl lg:mx-auto lg:grid lg:grid-cols-2 lg:gap-6 lg:items-start">
      {/* カレンダー（PCではカレンダーと予定一覧を左右に並べる / モバイルは縦積み） */}
      <div className="bg-surface rounded-2xl shadow-card hover:shadow-card-hover transition-shadow border border-border overflow-hidden mb-6 lg:mb-0">
        <div className="flex items-center justify-between px-4 py-3.5 bg-gradient-to-r from-brand to-brand-strong text-white font-bold">
          <button
            type="button"
            onClick={goPrevMonth}
            aria-label={t('schedule.prevMonth')}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 text-lg leading-none hover:bg-white/30 transition-colors focus:outline-none focus:ring-2 focus:ring-white/60"
          >
            ‹
          </button>
          <span className="text-lg tracking-wide">{monthTitle}</span>
          <button
            type="button"
            onClick={goNextMonth}
            aria-label={t('schedule.nextMonth')}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 text-lg leading-none hover:bg-white/30 transition-colors focus:outline-none focus:ring-2 focus:ring-white/60"
          >
            ›
          </button>
        </div>
        <div className="p-3">
          <div className="grid grid-cols-7 gap-1 mb-1">
            {WEEKDAY_LABELS[lang].map((w, i) => (
              <div
                key={w}
                className={`text-center text-xs font-bold py-1 ${
                  i === 0 ? 'text-brand' : i === 6 ? 'text-accent' : 'text-muted-foreground'
                }`}
              >
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
                'relative aspect-square rounded-xl flex flex-col items-center justify-center text-sm transition-all';
              const tone = inMonth ? 'text-foreground' : 'text-muted-foreground/50';
              let cls = `${base} ${tone}`;
              if (isSelected) {
                cls += ' bg-gradient-to-br from-brand to-brand-strong text-white font-bold shadow-card-hover scale-[1.04]';
              } else if (hasEvent) {
                cls += ' bg-brand-soft border border-accent-border font-semibold hover:bg-accent-bg hover:border-accent cursor-pointer';
              } else {
                cls += ' hover:bg-surface-muted';
              }
              if (isToday && !isSelected) {
                cls += ' ring-2 ring-brand ring-offset-1 ring-offset-surface bg-brand-soft/60';
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
                      className={`mt-0.5 h-1.5 w-1.5 rounded-full ${isSelected ? 'bg-white' : 'bg-accent'}`}
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

      {/* 予定一覧（PCではカレンダーの右、モバイルはカレンダーの下） */}
      <div className="bg-surface rounded-2xl shadow-card border border-border overflow-hidden mb-6 lg:mb-0">
        <div className="flex items-center gap-2 px-4 py-3 bg-accent-bg text-brand-strong font-bold border-b border-accent-border">
          <span aria-hidden className="text-lg">📅</span>
          <span>{t('schedule.listTitle')}</span>
          {selectedDate && (
            <button
              type="button"
              onClick={() => setSelectedDate(null)}
              className="ml-auto text-xs font-normal text-brand-strong underline hover:no-underline focus:outline-none focus:ring-2 focus:ring-brand/40 rounded"
            >
              {t('schedule.clearFilter')}
            </button>
          )}
        </div>
        <DatedInfoList
          items={listItems}
          isLoading={isLoading}
          namespace="schedule"
          beforeList={
            selectedDate ? (
              <p className="text-xs text-muted-foreground mb-2">
                {t('schedule.filteredBy')}
                {selectedDate}
              </p>
            ) : null
          }
        />
      </div>
    </div>
  );
};

export default SchedulePage;
