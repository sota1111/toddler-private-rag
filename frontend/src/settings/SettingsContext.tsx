import { useState, useCallback, type ReactNode } from 'react'
import {
  SettingsContext,
  DEFAULT_TIMEZONE,
  DEFAULT_MUNICIPALITY,
  type AppSettings,
} from './settingsContextValue'

// SOT-1315: 設定（タイムゾーン）を localStorage に永続化する。
// 既存の I18nContext と同じ保存方式に揃える。
// SOT-1403: 市町村も同じ方式で localStorage に永続化する。
const TZ_KEY = 'tpr.timezone'
const MUNI_KEY = 'tpr.municipality'

function getInitial(): AppSettings {
  if (typeof window === 'undefined') {
    return { timezone: DEFAULT_TIMEZONE, municipality: DEFAULT_MUNICIPALITY }
  }
  const tz = window.localStorage.getItem(TZ_KEY) || DEFAULT_TIMEZONE
  const municipality = window.localStorage.getItem(MUNI_KEY) ?? DEFAULT_MUNICIPALITY
  return { timezone: tz, municipality }
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

  const setMunicipality = useCallback((m: string) => {
    setSettings((prev) => ({ ...prev, municipality: m }))
    try {
      window.localStorage.setItem(MUNI_KEY, m)
    } catch {
      /* localStorage unavailable — keep in-memory only */
    }
  }, [])

  return (
    <SettingsContext.Provider
      value={{ ...settings, setTimezone, setMunicipality }}
    >
      {children}
    </SettingsContext.Provider>
  )
}
