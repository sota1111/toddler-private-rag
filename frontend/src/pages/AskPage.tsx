import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { askInfo, askInfoStream } from '../api';
import type { RagAnswer } from '../types';
import { useI18n } from '../i18n/useI18n';
import MarkdownText from '../components/MarkdownText';

// SOT-1286: 出典リンクで遷移→ブラウザ戻るで再マウントしても質問と回答が消えないよう、
// query と result を sessionStorage に保存・復元する。
const STORAGE_KEY = 'ask:lastSession';

type SavedSession = { query: string; result: RagAnswer | null };

const readSaved = (): SavedSession | null => {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SavedSession) : null;
  } catch {
    return null;
  }
};

const AskPage: React.FC = () => {
  const { t } = useI18n();
  const [query, setQuery] = useState<string>(() => readSaved()?.query ?? '');
  const [result, setResult] = useState<RagAnswer | null>(() => readSaved()?.result ?? null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // query / result が変わるたびに sessionStorage へ保存する（error / isLoading は一時状態なので保存しない）。
  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ query, result }));
    } catch {
      // sessionStorage 不在（プライベートモード等）でも落とさない
    }
  }, [query, result]);

  const runQuery = async (raw: string) => {
    const q = raw.trim();
    if (!q || isLoading) return;
    setIsLoading(true);
    setError(null);
    setResult(null);
    try {
      // SOT-1374 / C: まずストリーミングで回答を逐次表示し、体感待ち時間を縮める。
      let streamed = '';
      let streamedSources: RagAnswer['sources'] = [];
      const data = await askInfoStream(q, {
        onSources: (s) => {
          streamedSources = s;
          setResult({ answer: streamed, sources: s });
        },
        onToken: (text) => {
          streamed += text;
          setResult({ answer: streamed, sources: streamedSources });
        },
      });
      // ストリームが空(未対応/モック等)なら非ストリーミングにフォールバックする。
      setResult(data.answer.trim() ? data : await askInfo(q));
    } catch {
      // ストリーミング自体が失敗したら従来の /ask にフォールバックする。
      try {
        setResult(await askInfo(q));
      } catch {
        setError(t('ask.error'));
        setResult(null);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void runQuery(query);
  };

  // サンプル質問チップ（SOT-1020 / 提案1）。SOT-1413: タップしても自動送信はせず、
  // 入力欄に質問文を埋めて編集可能な状態にするだけにする（フォーカスを当てる）。
  const handleSample = (sample: string) => {
    setQuery(sample);
    textareaRef.current?.focus();
  };

  const SAMPLE_KEYS = ['ask.sample1', 'ask.sample2', 'ask.sample3'];

  // SOT-1412: ストリーミングでは sources イベントが先に届き、回答本文が空のまま result が
  // セットされる。回答トークンが届くまでは「生成中」表示を維持し、空の回答カード（空白時間）を
  // 出さないよう、回答本文の有無で表示を切り替える。
  const hasAnswer = !!result?.answer?.trim();

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('ask.title')}</h1>

      <form onSubmit={handleSubmit} className="bg-surface p-4 rounded-lg shadow-sm mb-6">
        <label htmlFor="ask-query" className="block text-sm font-medium text-foreground mb-1">
          {t('ask.label')}
        </label>
        <textarea
          ref={textareaRef}
          id="ask-query"
          rows={3}
          className="w-full border border-border rounded-md shadow-sm focus:ring-brand focus:border-brand sm:text-sm p-2"
          placeholder={t('ask.placeholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {/* サンプル質問チップ（提案1） */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">{t('ask.samplesLabel')}</span>
          {SAMPLE_KEYS.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => handleSample(t(k))}
              disabled={isLoading}
              className="rounded-full border border-border bg-brand-soft px-3 py-1 text-xs text-brand-strong hover:bg-brand-soft disabled:opacity-50 transition-colors"
            >
              {t(k)}
            </button>
          ))}
        </div>
        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className="px-4 py-2 rounded-md text-sm font-medium text-white bg-brand hover:bg-brand-strong disabled:bg-border disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? t('ask.submitting') : t('ask.submit')}
          </button>
        </div>
      </form>

      {error && (
        <div className="mb-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {error}
        </div>
      )}

      {isLoading && !hasAnswer && (
        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <span className="h-8 w-8 mb-3 rounded-full border-2 border-border border-t-blue-500 animate-spin" aria-hidden />
          <p className="text-sm">{t('ask.generating')}</p>
        </div>
      )}

      {!isLoading && !result && !error && (
        <div className="text-center py-12 text-muted-foreground">
          <div className="text-4xl mb-2" aria-hidden>💬</div>
          <p className="text-sm">{t('ask.emptyMain')}</p>
          <p className="text-xs mt-1">{t('ask.emptySub')}</p>
        </div>
      )}

      {result && (hasAnswer || !isLoading) && (
        <div className="space-y-6">
          <div className="bg-surface rounded-lg shadow-sm border border-border p-5">
            <h2 className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('ask.answer')}</h2>
            <MarkdownText text={result.answer} className="text-foreground" />
          </div>

          <div className="bg-surface rounded-lg shadow-sm border border-border p-5">
            <h2 className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-3">{t('ask.sources')}</h2>
            {result.sources.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('ask.noSources')}</p>
            ) : (
              <ul className="space-y-2">
                {result.sources.map((s, i) => (
                  <li
                    key={i}
                    className="p-3 rounded-md border border-border bg-surface-muted"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            s.source === 'ocr'
                              ? 'bg-purple-100 text-purple-800'
                              : 'bg-brand-soft text-brand-strong'
                          }`}
                        >
                          {s.source === 'ocr' ? t('ask.attached') : t('ask.body')}
                        </span>
                        {s.info_id != null && s.info_id !== '' ? (
                          <Link
                            to={`/data/${s.info_id}`}
                            className="text-sm text-brand-strong hover:underline truncate"
                          >
                            {s.label || s.title}
                          </Link>
                        ) : (
                          <span className="text-sm text-foreground truncate">{s.label || s.title}</span>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {t('ask.relevance')} {s.score.toFixed(2)}
                      </span>
                    </div>
                    {s.snippet && (
                      <blockquote className="mt-2 border-l-2 border-border pl-3 text-xs text-muted-foreground whitespace-pre-wrap break-words">
                        {t('ask.quoteLabel')}{s.snippet}
                      </blockquote>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AskPage;
