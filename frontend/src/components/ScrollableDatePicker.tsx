import React, { useMemo } from 'react';
import { useI18n } from '../i18n/useI18n';

// SOT-1307: 日付をスクロールで選択できるピッカー。年・月・日の3列を縦スクロール
// (scroll-snap) で選び、選択が変わるたびに 'YYYY-MM-DD'（ローカル日付・ゼロ埋め）を返す。
// 外部ライブラリは使わない。value は '' または 'YYYY-MM-DD'。

interface Props {
  value: string;
  onChange: (iso: string) => void;
  ariaLabel?: string;
}

const pad = (n: number): string => String(n).padStart(2, '0');

const daysInMonth = (year: number, month: number): number =>
  new Date(year, month, 0).getDate(); // month は 1-12

const ScrollableDatePicker: React.FC<Props> = ({ value, onChange, ariaLabel }) => {
  const { t } = useI18n();
  // 初回マウント時の今日を固定し、useMemo の依存が毎レンダー変わらないようにする。
  const today = useMemo(() => new Date(), []);

  // value をパースする。空なら今日を初期表示の基準にする（onChange は明示選択時のみ発火）。
  const parsed = useMemo(() => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '');
    if (m) {
      return { year: Number(m[1]), month: Number(m[2]), day: Number(m[3]) };
    }
    return { year: today.getFullYear(), month: today.getMonth() + 1, day: today.getDate() };
  }, [value, today]);

  const years = useMemo(() => {
    const base = today.getFullYear();
    const list: number[] = [];
    for (let y = base - 1; y <= base + 2; y += 1) list.push(y);
    return list;
  }, [today]);

  const months = useMemo(() => Array.from({ length: 12 }, (_, i) => i + 1), []);
  const days = useMemo(
    () => Array.from({ length: daysInMonth(parsed.year, parsed.month) }, (_, i) => i + 1),
    [parsed.year, parsed.month],
  );

  // 年/月/日のいずれかを変えたら 'YYYY-MM-DD' を組み立てて通知する。
  const emit = (year: number, month: number, day: number) => {
    const maxDay = daysInMonth(year, month);
    const clampedDay = Math.min(day, maxDay); // 月をまたいで存在しない日になったら丸める
    onChange(`${year}-${pad(month)}-${pad(clampedDay)}`);
  };

  const columnCls =
    'h-40 overflow-y-auto snap-y snap-mandatory rounded-md border border-border bg-surface text-center';
  const itemBase =
    'snap-center cursor-pointer py-2 text-sm transition-colors select-none';

  const renderColumn = (
    label: string,
    options: number[],
    selected: number,
    onSelect: (v: number) => void,
    suffix = '',
  ) => (
    <div className="flex-1 min-w-0">
      <p className="text-xs font-medium text-muted-foreground mb-1 text-center">{label}</p>
      <div className={columnCls} role="listbox" aria-label={label}>
        {options.map((v) => {
          const isSel = v === selected;
          return (
            <div
              key={v}
              role="option"
              aria-selected={isSel}
              onClick={() => onSelect(v)}
              className={`${itemBase} ${
                isSel
                  ? 'bg-brand text-white font-semibold'
                  : 'text-foreground hover:bg-surface-muted'
              }`}
            >
              {v}
              {suffix}
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="mt-1" aria-label={ariaLabel}>
      <div className="flex gap-2">
        {renderColumn(t('datePicker.year'), years, parsed.year, (y) =>
          emit(y, parsed.month, parsed.day),
        )}
        {renderColumn(t('datePicker.month'), months, parsed.month, (mo) =>
          emit(parsed.year, mo, parsed.day),
        )}
        {renderColumn(t('datePicker.day'), days, parsed.day, (d) =>
          emit(parsed.year, parsed.month, d),
        )}
      </div>
      <div className="flex items-center justify-between mt-2">
        <span className="text-sm text-foreground">
          {value ? value : <span className="text-muted-foreground">{t('datePicker.unset')}</span>}
        </span>
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="text-xs text-muted-foreground underline hover:no-underline"
          >
            {t('datePicker.clear')}
          </button>
        )}
      </div>
    </div>
  );
};

export default ScrollableDatePicker;
