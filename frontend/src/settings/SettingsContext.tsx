import { useState, useCallback, type ReactNode } from 'react'
import {
  SettingsContext,
  DEFAULT_TIMEZONE,
  type AppSettings,
} from './settingsContextValue'

// SOT-1315: 設定（タイムゾーン・子どもの名前）を localStorage に永続化する。
// 既存の I18nContext と同じ保存方式に揃える。
const TZ_KEY = 'tpr.timezone'
const CHILD_NAME_KEY = 'tpr.childName'

function getInitial(): AppSettings {
  if (typeof window === 'undefined') {
    return { timezone: DEFAULT_TIMEZONE, childName: '' }
  }
  const tz = window.localStorage.getItem(TZ_KEY) || DEFAULT_TIMEZONE
  const childName = window.localStorage.getItem(CHILD_NAME_KEY) || ''
  return { timezone: tz, childName }
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

  const setChildName = useCallback((name: string) => {
    setSettings((prev) => ({ ...prev, childName: name }))
    try {
      window.localStorage.setItem(CHILD_NAME_KEY, name)
    } catch {
      /* localStorage unavailable — keep in-memory only */
    }
  }, [])

  return (
    <SettingsContext.Provider
      value={{ ...settings, setTimezone, setChildName }}
    >
      {children}
    </SettingsContext.Provider>
  )
}
