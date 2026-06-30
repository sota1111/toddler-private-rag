import { createContext } from 'react'

// SOT-1315: 設定メニューで管理するユーザー設定。
// 言語(lang)は既存の i18n(I18nContext) が担うため、ここでは扱わない。
export interface AppSettings {
  /** 標準時間（タイムゾーン）。例: 'Asia/Tokyo' */
  timezone: string
  /** 市町村（ユーザーが設定する自治体名）。例: '渋谷区' */
  municipality: string
}

export interface SettingsContextType extends AppSettings {
  setTimezone: (tz: string) => void
  setMunicipality: (m: string) => void
}

export const DEFAULT_TIMEZONE = 'Asia/Tokyo'

// SOT-1403: 市町村は自由入力。既定は未設定（空文字）。
export const DEFAULT_MUNICIPALITY = ''

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
  municipality: DEFAULT_MUNICIPALITY,
  setTimezone: () => {},
  setMunicipality: () => {},
})
