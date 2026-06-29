import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

// ルート変更のたびにページ最上部へスクロールを戻す。
// react-router はデフォルトで遷移時のスクロール位置を維持するため、
// 一覧 → 詳細（/data/:id）などの遷移で前ページの位置が引き継がれ、
// 詳細画面が途中から表示されてしまう問題を防ぐ。
const ScrollToTop: React.FC = () => {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
};

export default ScrollToTop;
