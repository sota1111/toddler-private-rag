import { useI18n } from '../i18n/useI18n'

export default function LanguageToggle() {
  const { lang, setLang } = useI18n()
  return (
    <div
      className="inline-flex items-center rounded-md overflow-hidden border border-white/40 text-xs font-semibold"
      role="group"
      aria-label="Language"
    >
      <button
        type="button"
        onClick={() => setLang('ja')}
        aria-pressed={lang === 'ja'}
        className={`px-2 py-1 transition-colors ${
          lang === 'ja' ? 'bg-surface text-foreground' : 'text-white hover:bg-surface/20'
        }`}
      >
        JP
      </button>
      <button
        type="button"
        onClick={() => setLang('en')}
        aria-pressed={lang === 'en'}
        className={`px-2 py-1 transition-colors ${
          lang === 'en' ? 'bg-surface text-foreground' : 'text-white hover:bg-surface/20'
        }`}
      >
        EN
      </button>
    </div>
  )
}
