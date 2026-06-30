import React from 'react';

// SOT-1414: 質問の回答に含まれる Markdown を整形表示する軽量レンダラ。
// 依存を追加せず、見出し(#〜######)・**太字**・*/- 箇条書き（ネスト対応）・段落・
// http(s) URL のリンク化のみを対象にする（dangerouslySetInnerHTML は使わない）。
// URL のリンク化は DataDetailPage の LinkifiedText と同じパターンを踏襲する。

const URL_SPLIT_REGEX = /(https?:\/\/[^\s]+)/g;
const URL_TEST_REGEX = /^https?:\/\/[^\s]+$/;

// テキスト中の http(s) URL をクリック可能なリンクに変換する。
const linkify = (text: string, keyPrefix: string): React.ReactNode[] => {
  const parts = text.split(URL_SPLIT_REGEX);
  return parts.map((part, i) => {
    if (URL_TEST_REGEX.test(part)) {
      // 末尾の句読点はリンクに含めない（日本語本文対策）。
      const match = part.match(/^(.*?)([、。）)]*)$/s);
      const url = match ? match[1] : part;
      const trail = match ? match[2] : '';
      return (
        <React.Fragment key={`${keyPrefix}-u${i}`}>
          <a href={url} target="_blank" rel="noopener noreferrer" className="text-primary underline break-all">
            {url}
          </a>
          {trail}
        </React.Fragment>
      );
    }
    return <React.Fragment key={`${keyPrefix}-s${i}`}>{part}</React.Fragment>;
  });
};

// インライン: **太字** を <strong> にし、それ以外は URL リンク化する。
// ストリーミング中に閉じていない `**` が来ても、マッチしなければ素のテキストとして描画される。
const renderInline = (text: string, keyPrefix: string): React.ReactNode[] => {
  const segments = text.split(/(\*\*[^*]+\*\*)/g);
  const nodes: React.ReactNode[] = [];
  segments.forEach((seg, i) => {
    if (seg === '') return;
    const bold = seg.match(/^\*\*([^*]+)\*\*$/);
    if (bold) {
      nodes.push(
        <strong key={`${keyPrefix}-b${i}`} className="font-semibold">
          {linkify(bold[1], `${keyPrefix}-b${i}`)}
        </strong>,
      );
    } else {
      nodes.push(...linkify(seg, `${keyPrefix}-t${i}`));
    }
  });
  return nodes;
};

type ListNode = { text: string; children: ListNode[] };

type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; items: ListNode[] }
  | { kind: 'paragraph'; text: string };

const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const LIST_RE = /^(\s*)[*-]\s+(.*)$/;

// インデント量から箇条書きのネスト構造を組み立てる。
const buildNested = (flat: { indent: number; text: string }[]): ListNode[] => {
  const root: ListNode[] = [];
  const stack: { indent: number; children: ListNode[] }[] = [{ indent: -1, children: root }];
  for (const { indent, text } of flat) {
    const node: ListNode = { text, children: [] };
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }
    stack[stack.length - 1].children.push(node);
    stack.push({ indent, children: node.children });
  }
  return root;
};

const parseBlocks = (text: string): Block[] => {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (trimmed === '') {
      i += 1;
      continue;
    }
    const heading = trimmed.match(HEADING_RE);
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] });
      i += 1;
      continue;
    }
    if (LIST_RE.test(line)) {
      const flat: { indent: number; text: string }[] = [];
      while (i < lines.length) {
        const m = lines[i].match(LIST_RE);
        if (!m) break;
        flat.push({ indent: m[1].length, text: m[2] });
        i += 1;
      }
      blocks.push({ kind: 'list', items: buildNested(flat) });
      continue;
    }
    // 段落: 空行 / 見出し / 箇条書きが来るまでの連続行をまとめる。
    const paraLines: string[] = [];
    while (i < lines.length) {
      const l = lines[i];
      const tr = l.trim();
      if (tr === '' || HEADING_RE.test(tr) || LIST_RE.test(l)) break;
      paraLines.push(tr);
      i += 1;
    }
    blocks.push({ kind: 'paragraph', text: paraLines.join('\n') });
  }
  return blocks;
};

const headingClass = (level: number): string => {
  const base = 'font-bold text-foreground break-words';
  if (level <= 1) return `${base} text-xl mt-3 mb-1`;
  if (level === 2) return `${base} text-lg mt-3 mb-1`;
  if (level === 3) return `${base} text-base mt-3 mb-1`;
  return `${base} text-sm mt-2 mb-1`;
};

const renderList = (items: ListNode[], key: string): React.ReactNode => (
  <ul key={key} className="list-disc pl-5 space-y-1 my-1">
    {items.map((it, idx) => (
      <li key={`${key}-${idx}`} className="break-words">
        {renderInline(it.text, `${key}-${idx}`)}
        {it.children.length > 0 && renderList(it.children, `${key}-${idx}-c`)}
      </li>
    ))}
  </ul>
);

const MarkdownText: React.FC<{ text: string; className?: string }> = ({ text, className }) => {
  const blocks = parseBlocks(text);
  return (
    <div className={className}>
      {blocks.map((block, idx) => {
        const key = `blk-${idx}`;
        if (block.kind === 'heading') {
          return (
            <p key={key} className={headingClass(block.level)}>
              {renderInline(block.text, key)}
            </p>
          );
        }
        if (block.kind === 'list') {
          return renderList(block.items, key);
        }
        return (
          <p key={key} className="whitespace-pre-wrap leading-relaxed break-words my-1">
            {renderInline(block.text, key)}
          </p>
        );
      })}
    </div>
  );
};

export default MarkdownText;
