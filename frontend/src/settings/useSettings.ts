import { useContext } from 'react'
import { SettingsContext } from './settingsContextValue'

export function useSettings() {
  return useContext(SettingsContext)
}
