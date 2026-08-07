import React from 'react';
import type { MenuDay } from '../types';
import { useI18n } from '../i18n/useI18n';
import { pickMenuProtein } from '../utils/menuProtein';

// menu-calendar: カレンダーの「献立」モードで日付をタップしたときに、その日の献立を
// すべて表示するモーダル。カレンダーのセルは省スペースのため主菜1品のみを出し、詳細は
// ここで（給食・午前/午後おやつ・主要食材3色・栄養価）を表示する。

interface Props {
  day: MenuDay;
  onClose: () => void;
}

const List: React.FC<{ label: string; items?: string[] }> = ({ label, items }) => {
  if (!items || items.length === 0) return null;
  return (
    <div className="mb-2">
      <div className="text-xs font-bold text-brand-strong mb-0.5">{label}</div>
      <div className="text-sm text-foreground">{items.join(' / ')}</div>
    </div>
  );
};

const MenuDetailModal: React.FC<Props> = ({ day, onClose }) => {
  const { t } = useI18n();
  const mi = day.main_ingredients;
  const under3 = day.nutrition?.under3;
  const over3 = day.nutrition?.over3;
  const hasIngredients =
    mi && (mi.red.length || mi.yellow.length || mi.green.length || mi.other.length);
  const hasNutrition = Boolean(under3 || over3);

  const fmtNum = (v?: number | null): string =>
    v === null || v === undefined ? '—' : String(v);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full sm:max-w-md bg-surface rounded-t-2xl sm:rounded-2xl shadow-card-hover border border-border max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between px-4 py-3 bg-gradient-to-r from-brand to-brand-strong text-white font-bold">
          <span className="flex items-center gap-2">
            <span aria-hidden>{pickMenuProtein(day).icon}</span>
            <span>
              {day.date}
              {day.weekday ? `（${day.weekday}）` : ''}
            </span>
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('menu.close')}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-white/15 text-lg leading-none hover:bg-white/30 focus:outline-none focus:ring-2 focus:ring-white/60"
          >
            ×
          </button>
        </div>

        <div className="p-4">
          <List label={t('menu.morningSnack')} items={day.morning_snack} />
          <List label={t('menu.lunch')} items={day.lunch} />
          <List label={t('menu.afternoonSnack')} items={day.afternoon_snack} />

          {hasIngredients ? (
            <div className="mt-3 border-t border-border pt-3">
              <div className="text-xs font-bold text-muted-foreground mb-1">
                {t('menu.ingredients')}
              </div>
              <List label={`🔴 ${t('menu.ingRed')}`} items={mi.red} />
              <List label={`🟡 ${t('menu.ingYellow')}`} items={mi.yellow} />
              <List label={`🟢 ${t('menu.ingGreen')}`} items={mi.green} />
              <List label={t('menu.ingOther')} items={mi.other} />
            </div>
          ) : null}

          {hasNutrition ? (
            <div className="mt-3 border-t border-border pt-3">
              <div className="text-xs font-bold text-muted-foreground mb-1">
                {t('menu.nutrition')}
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="text-left font-normal" />
                    <th className="text-right font-normal">{t('menu.energy')}</th>
                    <th className="text-right font-normal">{t('menu.protein')}</th>
                    <th className="text-right font-normal">{t('menu.fat')}</th>
                  </tr>
                </thead>
                <tbody>
                  {under3 ? (
                    <tr>
                      <td className="text-brand-strong">{t('menu.under3')}</td>
                      <td className="text-right">{fmtNum(under3.energy_kcal)} kcal</td>
                      <td className="text-right">{fmtNum(under3.protein_g)} g</td>
                      <td className="text-right">{fmtNum(under3.fat_g)} g</td>
                    </tr>
                  ) : null}
                  {over3 ? (
                    <tr>
                      <td className="text-brand-strong">{t('menu.over3')}</td>
                      <td className="text-right">{fmtNum(over3.energy_kcal)} kcal</td>
                      <td className="text-right">{fmtNum(over3.protein_g)} g</td>
                      <td className="text-right">{fmtNum(over3.fat_g)} g</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export default MenuDetailModal;
