import { useState, useCallback, type ReactNode } from 'react'
import { I18nContext, type Lang } from './i18nContextValue'
import { messages } from './messages'

const STORAGE_KEY = 'tpr.lang'

function getInitialLang(): Lang {
  if (typeof window === 'undefined') return 'ja'
  const saved = window.localStorage.getItem(STORAGE_KEY)
  return saved === 'en' || saved === 'ja' ? saved : 'ja'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(getInitialLang)

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* localStorage unavailable — keep in-memory only */
    }
  }, [])

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      const dict = messages[lang] ?? messages.ja
      let str = dict[key] ?? messages.ja[key] ?? key
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
        }
      }
      return str
    },
    [lang],
  )

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  )
}
