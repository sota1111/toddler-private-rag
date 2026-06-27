import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/useAuth';
import { I18nProvider } from './i18n/I18nContext';
import { useI18n } from './i18n/useI18n';
import { RoleProvider } from './contexts/RoleContext';
import { SettingsProvider } from './settings/SettingsContext';
import LanguageToggle from './components/LanguageToggle';
import RoleToggle from './components/RoleToggle';
import ReminderBanner from './components/ReminderBanner';
import ProtectedRoute from './components/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import AutoRegisterPage from './pages/AutoRegisterPage';
import InfoHubPage from './pages/InfoHubPage';
import DraftsPage from './pages/DraftsPage';
import DataDetailPage from './pages/DataDetailPage';
import SchedulePage from './pages/SchedulePage';
import TasksPage from './pages/TasksPage';
import SettingsPage from './pages/SettingsPage';

const queryClient = new QueryClient();

// 階段トレーニング（shrine-stair-trainer）のメニューに合わせ、各項目をアイコン＋文字で表示する。
// アイコンは currentColor の線画SVGで統一し、active/hover の文字色がそのまま反映される。
const navIconProps = {
  width: 22,
  height: 22,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
};

const DashboardIcon = () => (
  <svg {...navIconProps}><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>
);
const InfoIcon = () => (
  <svg {...navIconProps}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /><path d="M8 13h8" /><path d="M8 17h6" /></svg>
);
const CreateIcon = () => (
  <svg {...navIconProps}><circle cx="12" cy="12" r="9" /><path d="M12 8v8" /><path d="M8 12h8" /></svg>
);
const ScheduleIcon = () => (
  <svg {...navIconProps}><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /><line x1="8" y1="14" x2="8" y2="14" /><line x1="12" y1="14" x2="12" y2="14" /><line x1="16" y1="14" x2="16" y2="14" /></svg>
);
const TasksIcon = () => (
  <svg {...navIconProps}><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>
);
const SettingsIcon = () => (
  <svg {...navIconProps}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
);

const NavLink: React.FC<{
  to: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  activeWhen?: (pathname: string) => boolean;
}> = ({ to, icon, children, activeWhen }) => {
  const location = useLocation();
  const isActive = activeWhen ? activeWhen(location.pathname) : location.pathname === to;
  return (
    <Link
      to={to}
      className={`flex flex-shrink-0 flex-col items-center gap-0.5 whitespace-nowrap px-3.5 py-1.5 rounded-2xl text-xs font-semibold ${
        isActive ? 'bg-surface/25 text-white' : 'text-white/80 hover:bg-surface/15 hover:text-white'
      } transition-colors`}
    >
      <span className="flex items-center justify-center md:hidden">{icon}</span>
      <span>{children}</span>
    </Link>
  );
};

const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, email, logout } = useAuth();
  const { t } = useI18n();

  return (
    <div className={`min-h-screen bg-surface-muted font-sans text-foreground ${isAuthenticated ? 'pb-16 md:pb-0' : ''}`}>
      {!isAuthenticated && (
        // ログイン前はタイトルと言語切替のみを表示する（SOT-1302）。
        // ナビメニュー・ロール切替・ログアウトは認証後のみ。
        <nav className="bg-gradient-to-r from-brand to-brand-strong shadow-md sticky top-0 z-20">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <div className="flex-shrink-0 flex items-center gap-2 text-white font-bold text-xl">
                {t('app.title')}
              </div>
              <LanguageToggle />
            </div>
          </div>
        </nav>
      )}
      {isAuthenticated && (
      <nav className="bg-gradient-to-r from-brand to-brand-strong shadow-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center min-w-0">
              <div className="flex-shrink-0 flex items-center gap-2 text-white font-bold text-xl">
                {t('app.title')}
              </div>
            </div>
            <div className="flex items-center gap-2 md:gap-3">
              <RoleToggle />
              <LanguageToggle />
              {isAuthenticated && (
                <div className="flex items-center gap-2 md:gap-3">
                  <span className="hidden md:inline text-white/80 text-sm">{email}</span>
                  <button
                    type="button"
                    onClick={logout}
                    aria-label={t('nav.logout')}
                    title={t('nav.logout')}
                    className="flex-shrink-0 inline-flex items-center justify-center text-white/80 hover:text-white p-2 rounded-full hover:bg-surface/15"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
                      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                      <polyline points="16 17 21 12 16 7" />
                      <line x1="21" y1="12" x2="9" y2="12" />
                    </svg>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
        {isAuthenticated && (
          <div className="border-t border-white/10 fixed bottom-0 left-0 right-0 z-20 bg-gradient-to-r from-brand to-brand-strong shadow-[0_-2px_8px_rgba(0,0,0,0.18)] md:static md:bg-transparent md:shadow-none">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex items-center justify-center md:justify-start gap-2 overflow-x-auto whitespace-nowrap py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                <NavLink to="/" icon={<DashboardIcon />}>{t('nav.dashboard')}</NavLink>
                <NavLink to="/info" icon={<InfoIcon />}>{t('nav.info')}</NavLink>
                <NavLink
                  to="/create/auto"
                  icon={<CreateIcon />}
                  activeWhen={(p) => p.startsWith('/create') || p === '/drafts'}
                >
                  {t('nav.create')}
                </NavLink>
                <NavLink to="/schedule" icon={<ScheduleIcon />}>{t('nav.schedule')}</NavLink>
                <NavLink to="/tasks" icon={<TasksIcon />}>{t('nav.tasks')}</NavLink>
                <NavLink to="/settings" icon={<SettingsIcon />}>{t('nav.settings')}</NavLink>
              </div>
            </div>
          </div>
        )}
      </nav>
      )}
      {isAuthenticated && <ReminderBanner />}
      <main className="max-w-7xl mx-auto py-6 px-4 lg:px-8">{children}</main>
      <footer className="bg-surface border-t border-border py-4 mt-10">
        <div className="text-center text-muted-foreground text-sm">{t('footer.copyright')}</div>
      </footer>
    </div>
  );
};

const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <SettingsProvider>
        <RoleProvider>
          <AuthProvider>
            <Router>
            <Layout>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
                <Route path="/info" element={<ProtectedRoute><InfoHubPage /></ProtectedRoute>} />
                <Route path="/data/:id" element={<ProtectedRoute><DataDetailPage /></ProtectedRoute>} />
                <Route path="/drafts" element={<ProtectedRoute><DraftsPage /></ProtectedRoute>} />
                <Route path="/schedule" element={<ProtectedRoute><SchedulePage /></ProtectedRoute>} />
                <Route path="/tasks" element={<ProtectedRoute><TasksPage /></ProtectedRoute>} />
                <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
                <Route path="/ask" element={<Navigate to="/info?tab=ask" replace />} />
                <Route path="/search" element={<Navigate to="/info?tab=search" replace />} />
                <Route path="/list" element={<Navigate to="/info?tab=list" replace />} />
                <Route
                  path="/create/*"
                  element={
                    <ProtectedRoute>
                      <Routes>
                        <Route index element={<Navigate to="/create/auto" replace />} />
                        <Route path="auto" element={<AutoRegisterPage />} />
                        <Route path="*" element={<Navigate to="/create/auto" replace />} />
                      </Routes>
                    </ProtectedRoute>
                  }
                />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Layout>
            </Router>
          </AuthProvider>
        </RoleProvider>
        </SettingsProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
};

export default App;
