import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getReminders } from '../api';
import type { ReminderItem } from '../types';
import { useI18n } from '../i18n/useI18n';

// SOT-1080 / 提案5-A: アプリ全体の能動リマインドバナー。
// overdue + today の緊急件数を要約し、ダッシュボードへ誘導する。
// ブラウザ通知が許可されていれば、起動中に緊急リマインドを能動pushする。
const notificationsSupported = (): boolean =>
  typeof window !== 'undefined' && 'Notification' in window;

const ReminderBanner: React.FC = () => {
  const { t } = useI18n();
  const [dismissed, setDismissed] = React.useState(false);
  // 起動中の重複通知を避けるためのフラグ（再レンダリング不要なので ref）。
  const notifiedRef = React.useRef(false);

  const { data } = useQuery({
    queryKey: ['reminders'],
    queryFn: () => getReminders(7),
  });

  const urgentItems: ReminderItem[] = React.useMemo(
    () => (data?.items ?? []).filter((r) => r.urgency === 'overdue' || r.urgency === 'today'),
    [data],
  );
  const urgentCount = urgentItems.length;

  const pushNotification = React.useCallback(() => {
    if (!notificationsSupported() || Notification.permission !== 'granted') return;
    if (notifiedRef.current || urgentItems.length === 0) return;
    try {
      const top = urgentItems.slice(0, 3).map((r) => r.message).join('\n');
      new Notification(t('reminder.title'), { body: top });
      notifiedRef.current = true;
    } catch {
      /* notification unavailable — skip silently */
    }
  }, [urgentItems, t]);

  // 許可済みなら起動中に一度だけ能動push
  React.useEffect(() => {
    if (urgentCount > 0) pushNotification();
  }, [urgentCount, pushNotification]);

  const enableNotifications = () => {
    if (!notificationsSupported()) return;
    Notification.requestPermission()
      .then(() => pushNotification())
      .catch(() => {
        /* permission flow failed — skip silently */
      });
  };

  if (urgentCount === 0 || dismissed) return null;

  const canEnable =
    notificationsSupported() && Notification.permission === 'default';

  return (
    <div className="bg-rose-50 border-b border-rose-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2 flex items-center gap-3 flex-wrap">
        <span aria-hidden className="text-lg">🔔</span>
        <span className="text-sm font-semibold text-rose-800">
          {t('reminder.bannerUrgent', { n: urgentCount })}
        </span>
        <Link
          to="/"
          className="text-sm font-semibold text-rose-700 underline hover:text-rose-900"
        >
          {t('reminder.view')}
        </Link>
        {canEnable && (
          <button
            type="button"
            onClick={enableNotifications}
            className="text-xs px-2 py-1 rounded-full bg-surface text-rose-700 border border-rose-300 hover:bg-rose-100"
          >
            {t('reminder.enableNotifications')}
          </button>
        )}
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="ml-auto text-xs text-rose-600 hover:text-rose-800"
        >
          {t('reminder.dismiss')}
        </button>
      </div>
    </div>
  );
};

export default ReminderBanner;
