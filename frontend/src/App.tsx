import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/useAuth';
import { I18nProvider } from './i18n/I18nContext';
import { useI18n } from './i18n/useI18n';
import LanguageToggle from './components/LanguageToggle';
import ProtectedRoute from './components/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import InfoListPage from './pages/InfoListPage';
import InfoCreatePage from './pages/InfoCreatePage';
import AskPage from './pages/AskPage';

const queryClient = new QueryClient();

const NavLink: React.FC<{ to: string; children: React.ReactNode }> = ({ to, children }) => {
  const location = useLocation();
  const isActive = location.pathname === to;
  return (
    <Link
      to={to}
      className={`flex-shrink-0 whitespace-nowrap px-3 py-2 rounded-md text-sm font-medium ${
        isActive ? 'bg-blue-700 text-white' : 'text-blue-100 hover:bg-blue-600 hover:text-white'
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
    <div className="min-h-screen bg-gray-100">
      <nav className="bg-gradient-to-r from-blue-600 to-indigo-600 shadow-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center min-w-0">
              <div className="flex-shrink-0 flex items-center gap-2 text-white font-bold text-xl">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-white/20 text-lg" aria-hidden>🏫</span>
                {t('app.title')}
              </div>
            </div>
            <div className="flex items-center gap-2 md:gap-3">
              <LanguageToggle />
              {isAuthenticated && (
                <div className="flex items-center gap-2 md:gap-3">
                  <span className="hidden md:inline text-blue-100 text-sm">{email}</span>
                  <button onClick={logout} className="flex-shrink-0 text-blue-100 hover:text-white text-sm px-3 py-1 rounded hover:bg-blue-600">{t('nav.logout')}</button>
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
        <AuthProvider>
          <Router>
            <Layout>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
                <Route path="/ask" element={<ProtectedRoute><AskPage /></ProtectedRoute>} />
                <Route path="/list" element={<ProtectedRoute><InfoListPage /></ProtectedRoute>} />
                <Route path="/create" element={<ProtectedRoute><InfoCreatePage /></ProtectedRoute>} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Layout>
          </Router>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
};

export default App;
