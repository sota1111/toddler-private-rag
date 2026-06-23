import { useI18n } from '../i18n/useI18n'
import { useRole } from '../contexts/useRole'

export default function RoleToggle() {
  const { t } = useI18n()
  const { role, setRole } = useRole()
  return (
    <div
      className="inline-flex items-center rounded-md overflow-hidden border border-white/40 text-xs font-semibold"
      role="group"
      aria-label={t('role.label')}
    >
      <button
        type="button"
        onClick={() => setRole('admin')}
        aria-pressed={role === 'admin'}
        className={`px-2 py-1 transition-colors ${
          role === 'admin' ? 'bg-surface text-foreground' : 'text-white hover:bg-surface/20'
        }`}
      >
        {t('role.admin')}
      </button>
      <button
        type="button"
        onClick={() => setRole('user')}
        aria-pressed={role === 'user'}
        className={`px-2 py-1 transition-colors ${
          role === 'user' ? 'bg-surface text-foreground' : 'text-white hover:bg-surface/20'
        }`}
      >
        {t('role.user')}
      </button>
    </div>
  )
}
