import { createContext } from 'react'

export type Lang = 'ja' | 'en'

export interface I18nContextType {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: string, vars?: Record<string, string | number>) => string
}

export const I18nContext = createContext<I18nContextType>({
  lang: 'ja',
  setLang: () => {},
  t: (key) => key,
})
