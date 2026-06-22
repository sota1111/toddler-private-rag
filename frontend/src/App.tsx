import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/useAuth';
import { I18nProvider } from './i18n/I18nContext';
import { useI18n } from './i18n/useI18n';
import { RoleProvider } from './contexts/RoleContext';
import LanguageToggle from './components/LanguageToggle';
import RoleToggle from './components/RoleToggle';
import ProtectedRoute from './components/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import InfoListPage from './pages/InfoListPage';
import InfoCreatePage from './pages/InfoCreatePage';
import DraftConfirmPage from './pages/DraftConfirmPage';
import RegisterConfirmPage from './pages/RegisterConfirmPage';
import AskPage from './pages/AskPage';
import { CreateFlowProvider } from './contexts/CreateFlowContext';

const queryClient = new QueryClient();

const NavLink: React.FC<{ to: string; children: React.ReactNode }> = ({ to, children }) => {
  const location = useLocation();
  const isActive = location.pathname === to;
  return (
    <Link
      to={to}
      className={`flex-shrink-0 whitespace-nowrap px-3.5 py-2 rounded-full text-sm font-semibold ${
        isActive ? 'bg-white/25 text-white' : 'text-white/80 hover:bg-white/15 hover:text-white'
      } transition-colors`}
    >
      {children}
    </Link>
  );
};

const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, email, logout } = useAuth();
  const { t } = useI18n();

  return (
    <div className="min-h-screen bg-surface-muted font-sans text-slate-800">
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
                    className="flex-shrink-0 inline-flex items-center justify-center text-white/80 hover:text-white p-2 rounded-full hover:bg-white/15"
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
          <div className="border-t border-white/10">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex items-center gap-2 overflow-x-auto whitespace-nowrap py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                <NavLink to="/">{t('nav.dashboard')}</NavLink>
                <NavLink to="/ask">{t('nav.ask')}</NavLink>
                <NavLink to="/list">{t('nav.list')}</NavLink>
                <NavLink to="/create">{t('nav.create')}</NavLink>
              </div>
            </div>
          </div>
        )}
      </nav>
      <main className="max-w-7xl mx-auto py-6 px-4 lg:px-8">{children}</main>
      <footer className="bg-white border-t border-gray-200 py-4 mt-10">
        <div className="text-center text-gray-500 text-sm">{t('footer.copyright')}</div>
      </footer>
    </div>
  );
};

const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RoleProvider>
          <AuthProvider>
            <Router>
            <Layout>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
                <Route path="/ask" element={<ProtectedRoute><AskPage /></ProtectedRoute>} />
                <Route path="/list" element={<ProtectedRoute><InfoListPage /></ProtectedRoute>} />
                <Route
                  path="/create/*"
                  element={
                    <ProtectedRoute>
                      <CreateFlowProvider>
                        <Routes>
                          <Route index element={<InfoCreatePage />} />
                          <Route path="confirm-draft" element={<DraftConfirmPage />} />
                          <Route path="confirm-register" element={<RegisterConfirmPage />} />
                          <Route path="*" element={<Navigate to="/create" replace />} />
                        </Routes>
                      </CreateFlowProvider>
                    </ProtectedRoute>
                  }
                />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Layout>
            </Router>
          </AuthProvider>
        </RoleProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
};

export default App;
