import { createContext } from 'react'

// SOT-1315: 設定メニューで管理するユーザー設定。
// 言語(lang)は既存の i18n(I18nContext) が担うため、ここでは扱わない。
export interface AppSettings {
  /** 標準時間（タイムゾーン）。例: 'Asia/Tokyo' */
  timezone: string
}

export interface SettingsContextType extends AppSettings {
  setTimezone: (tz: string) => void
}

export const DEFAULT_TIMEZONE = 'Asia/Tokyo'

// 設定画面で選べるタイムゾーン候補（最小限）。
export const TIMEZONE_OPTIONS = [
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Asia/Seoul',
  'America/Los_Angeles',
  'America/New_York',
  'Europe/London',
  'UTC',
] as const

export const SettingsContext = createContext<SettingsContextType>({
  timezone: DEFAULT_TIMEZONE,
  setTimezone: () => {},
})
