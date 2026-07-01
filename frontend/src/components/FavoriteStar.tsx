import React from 'react';

// SOT-1428: お気に入り表示用の星アイコン（プレゼンテーションのみ）。
// やることリストのトグルボタンの中身と、掲示板の表示専用インジケータの両方で再利用する。
// アイコンライブラリは導入していないためインライン SVG を使う。
// filled=true でお気に入り（黄色塗り潰し）、false で枠線のみ（中抜き）。
const FavoriteStar: React.FC<{ filled: boolean; className?: string }> = ({ filled, className }) => (
  <svg
    viewBox="0 0 24 24"
    aria-hidden
    className={`h-5 w-5 ${filled ? 'text-yellow-400' : 'text-muted-foreground'} ${className ?? ''}`}
    fill={filled ? 'currentColor' : 'none'}
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M12 2.5l2.95 5.98 6.6.96-4.78 4.66 1.13 6.57L12 17.56l-5.9 3.1 1.13-6.57L2.45 9.44l6.6-.96L12 2.5z" />
  </svg>
);

export default FavoriteStar;
