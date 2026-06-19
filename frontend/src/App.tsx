import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/useAuth';
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
      className={`px-3 py-2 rounded-md text-sm font-medium ${
        isActive ? 'bg-blue-700 text-white' : 'text-blue-100 hover:bg-blue-600 hover:text-white'
      } transition-colors`}
    >
      {children}
    </Link>
  );
};

const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, email, logout } = useAuth();
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  return (
    <div className="min-h-screen bg-gray-100">
      <nav className="bg-gradient-to-r from-blue-600 to-indigo-600 shadow-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center">
              <div className="flex-shrink-0 flex items-center gap-2 text-white font-bold text-xl">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-white/20 text-lg" aria-hidden>🏫</span>
                保育園アシスタント
              </div>
              <div className="hidden md:flex ml-10 items-baseline space-x-4">
                {isAuthenticated && (
                  <>
                    <NavLink to="/">ダッシュボード</NavLink>
                    <NavLink to="/ask">質問</NavLink>
                    <NavLink to="/list">一覧</NavLink>
                    <NavLink to="/create">登録</NavLink>
                  </>
                )}
              </div>
            </div>
            <div className="hidden md:flex items-center space-x-3">
              {isAuthenticated && (
                <>
                  <span className="text-blue-100 text-sm">{email}</span>
                  <button onClick={logout} className="text-blue-100 hover:text-white text-sm px-3 py-1 rounded hover:bg-blue-600">ログアウト</button>
                </>
              )}
            </div>
            <div className="md:hidden">
              <button onClick={() => setIsMenuOpen(!isMenuOpen)} className="text-white hover:text-gray-200 focus:outline-none">
                <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  {isMenuOpen ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" />
                  )}
                </svg>
              </button>
            </div>
          </div>
        </div>
        {isMenuOpen && isAuthenticated && (
          <div className="md:hidden bg-blue-600 px-2 pt-2 pb-3 space-y-1 sm:px-3">
            <Link to="/" onClick={() => setIsMenuOpen(false)} className="block px-3 py-2 rounded-md text-base font-medium text-white hover:bg-blue-700">ダッシュボード</Link>
            <Link to="/ask" onClick={() => setIsMenuOpen(false)} className="block px-3 py-2 rounded-md text-base font-medium text-white hover:bg-blue-700">質問</Link>
            <Link to="/list" onClick={() => setIsMenuOpen(false)} className="block px-3 py-2 rounded-md text-base font-medium text-white hover:bg-blue-700">一覧</Link>
            <Link to="/create" onClick={() => setIsMenuOpen(false)} className="block px-3 py-2 rounded-md text-base font-medium text-white hover:bg-blue-700">登録</Link>
            <button onClick={() => { logout(); setIsMenuOpen(false); }} className="block w-full text-left px-3 py-2 rounded-md text-base font-medium text-white hover:bg-blue-700">ログアウト</button>
          </div>
        )}
      </nav>
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">{children}</main>
      <footer className="bg-white border-t border-gray-200 py-4 mt-10">
        <div className="text-center text-gray-500 text-sm">&copy; 2026 保育園情報アシスタント MVP</div>
      </footer>
    </div>
  );
};

const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
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
    </QueryClientProvider>
  );
};

export default App;
