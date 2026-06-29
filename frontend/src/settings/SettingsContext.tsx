import { useState, useCallback, type ReactNode } from 'react'
import {
  SettingsContext,
  DEFAULT_TIMEZONE,
  type AppSettings,
} from './settingsContextValue'

// SOT-1315: 設定（タイムゾーン）を localStorage に永続化する。
// 既存の I18nContext と同じ保存方式に揃える。
const TZ_KEY = 'tpr.timezone'

function getInitial(): AppSettings {
  if (typeof window === 'undefined') {
    return { timezone: DEFAULT_TIMEZONE }
  }
  const tz = window.localStorage.getItem(TZ_KEY) || DEFAULT_TIMEZONE
  return { timezone: tz }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(getInitial)

  const setTimezone = useCallback((tz: string) => {
    setSettings((prev) => ({ ...prev, timezone: tz }))
    try {
      window.localStorage.setItem(TZ_KEY, tz)
    } catch {
      /* localStorage unavailable — keep in-memory only */
    }
  }, [])

  return (
    <SettingsContext.Provider
      value={{ ...settings, setTimezone }}
    >
      {children}
    </SettingsContext.Provider>
  )
}
