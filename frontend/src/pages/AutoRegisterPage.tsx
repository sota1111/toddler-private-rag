import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createInfo, uploadAttachment, getInfoById } from '../api';
import type { NurseryInfo, NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { compressImageFile } from '../utils/imageCompression';
import RegisterMenu from '../components/RegisterMenu';

// 自動登録 = データ登録 (SOT-1052 / SOT-1113)
// 写真を選ぶとOCRで内容を読み取り、仮登録(draft)として永続化する。
// SOT-1293: enrich(JSON生成)→Firestore永続化→draft昇格はサーバ側で行う。ブラウザは
// createInfo(processing)+写真アップのみを行い、以降はサーバ任せ（タブを閉じても仮登録に出る）。
// 完了表示のため、サーバ側の draft 昇格をポーリングで待って結果を反映する。
type Phase = 'idle' | 'confirm' | 'saving' | 'done';

const AutoRegisterPage: React.FC = () => {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const photoInputRef = useRef<HTMLInputElement>(null);
  // SOT-1289: 文字起こし整理中でも次の写真を追加できる。並行アップロード時、
  // 進行中だった前のアップロードの setState（特に finally の done 昇格）が
  // 新しいアップロードの画面状態を上書きしないよう、世代カウンタで最新のみ反映する。
  const uploadSeqRef = useRef(0);
  // SOT-1322: 「写真をアップしています…」表示を短くするため、画像圧縮(端末側で数秒かかる)を
  // 確認フェーズ(プレビュー表示中)で先行実行しておく。圧縮はキャンセル不可なので Promise を
  // 保持し、アップロード確定時に最新のものを await して再利用する(間に合っていなければ従来同様に待つ)。
  const compressedRef = useRef<Promise<File> | null>(null);
  // 'idle' 入力待ち / 'confirm' 写真確認待ち / 'saving' 仮登録保存中 / 'done' 完了
  // SOT-1322: アップロード成功＝写真は保存済みなので即 'done'。整理(OCR/enrich)はサーバ側の
  // バックグラウンドで進み、完了したら done カードのタイトル/本文をバックグラウンドで更新する。
  const [phase, setPhase] = useState<Phase>('idle');
  const [extractError, setExtractError] = useState<string | null>(null);
  const [savedDraft, setSavedDraft] = useState<NurseryInfo | null>(null);
  // 文字起こし/整理(enrich)に失敗したか（写真は保存済み）
  const [enrichFailed, setEnrichFailed] = useState(false);
  // SOT-1288: アップ前に「この写真で良いか」を確認する。確定するまでサーバ保存しない。
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // プレビュー用の objectURL を破棄する（不要になった時点で必ず呼ぶ）
  const clearPreview = () => {
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setPendingFile(null);
  };

  // アンマウント時に objectURL を解放する
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const resetForAnother = () => {
    // SOT-1322: 進行中のバックグラウンドポーリングを無効化し、idle 画面を上書きさせない
    uploadSeqRef.current += 1;
    clearPreview();
    // SOT-1322: 先行圧縮結果をクリア
    compressedRef.current = null;
    setSavedDraft(null);
    setExtractError(null);
    setEnrichFailed(false);
    setPhase('idle');
  };

  // 写真を選択したら確認画面へ。まだアップロードは始めない (SOT-1288)。
  const handlePhotoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // input をリセットして同じファイルでも再選択できるようにする
    if (photoInputRef.current) photoInputRef.current.value = '';
    if (!file) return;

    // SOT-1322: 進行中のバックグラウンドポーリングを無効化し、新しい写真の画面を上書きさせない
    uploadSeqRef.current += 1;
    setExtractError(null);
    setSavedDraft(null);
    setEnrichFailed(false);
    // 既存のプレビューがあれば破棄してから新しいものを保持する
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPendingFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    // SOT-1322: 確認中に画像圧縮を先行実行しておく(失敗時は元ファイルにフォールバックし throw しない)。
    // 古い圧縮結果を使わないよう、新しい file の圧縮で必ず上書きする。
    compressedRef.current = compressImageFile(file);
    setPhase('confirm');
  };

  // 「選び直す」: 確認待ちの写真を破棄して入力待ちに戻す（サーバ保存はしていない）
  const handleRetake = () => {
    // SOT-1322: 進行中のバックグラウンドポーリングを無効化する
    uploadSeqRef.current += 1;
    clearPreview();
    // SOT-1322: 破棄した写真の先行圧縮結果は使わない
    compressedRef.current = null;
    setPhase('idle');
  };

  // 確認画面で「この写真で登録」を押したときに初めてアップロード・仮登録を開始する。
  const startUpload = async (file: File) => {
    // SOT-1289: このアップロードの世代を採番。以降の画面状態(setState)更新は、
    // 自分が最新世代のときだけ反映する（保存処理 createInfo/uploadAttachment 自体は
    // 全写真分そのまま実行する）。
    const seq = ++uploadSeqRef.current;
    const isCurrent = () => uploadSeqRef.current === seq;
    const applyIfCurrent = (fn: () => void) => {
      if (isCurrent()) fn();
    };

    // プレビューはここで破棄してよい（保存処理は圧縮後ファイルを使う）
    clearPreview();
    setExtractError(null);
    setSavedDraft(null);
    setEnrichFailed(false);
    setPhase('saving');

    // アップロード前に圧縮・JPEG変換し、OCR・添付ともに変換後ファイルのみを使う（生データは保持しない）
    // 圧縮は失敗しても元ファイルにフォールバックするため throw しない。
    // SOT-1322: 確認フェーズで先行実行した圧縮があれば再利用し、「写真をアップしています…」表示中の
    // 圧縮待ちを無くす。間に合っていなければここで待つだけなので従来と同等（退行なし）。
    const processed = await (compressedRef.current ?? compressImageFile(file));
    compressedRef.current = null;

    // SOT-1175: 「画像アップ完了をトリガーに画像変換と仮登録を始める」。
    // 重い画像変換(OCR/AI抽出)を待たずに、まず最小限の仮登録(processing)と写真添付を保存する。
    let created: NurseryInfo;
    try {
      const initial: NurseryInfoCreate = {
        title: '',
        info_type: '資料',
        content: '',
        date: '',
        event_date: '',
        due_date: '',
        items: '',
        status: '未対応',
        priority: '普通',
        tags: '',
        memo: '',
        // SOT-1272/SOT-1293: enrich が完了するまでは仮登録一覧に出さない。
        // まず非表示の処理中状態(processing)で保存する。サーバ側の OCR background task が
        // enrich→draft 昇格まで行うため、ここで write を続ける必要はない。
        registration_state: 'processing',
      };

      // 仮登録を保存し、写真を添付する（ここまで成功＝データは失われない）。
      // 写真アップロードがサーバ側 enrich→draft 昇格のトリガーになる。
      created = await createInfo(initial);
      // SOT-1315: 設定言語(lang)を渡し、文字起こし後のタスク登録をその言語で生成させる。
      await uploadAttachment(created.id, processed, lang);
      // SOT-1322: アップロード成功＝写真はサーバ保存済み。整理(OCR/enrich)はサーバ側の
      // バックグラウンドで進むため、ユーザーを待たせず即「完了」表示にする。
      applyIfCurrent(() => {
        setSavedDraft(created);
        setPhase('done');
      });
    } catch (error) {
      console.error('Failed to save draft/photo on upload', error);
      applyIfCurrent(() => {
        setExtractError(t('create.autoSaveFail'));
        setPhase('idle');
      });
      return;
    }

    // SOT-1293/SOT-1324: enrich(JSON生成)→Firestore永続化→登録昇格はサーバ側で進む。
    // SOT-1322: ユーザーは既に完了画面にいる。バックグラウンドで登録昇格をポーリングし、
    // 完了したら完了カードのタイトル/本文だけを更新する（待ち画面で足止めしない）。
    // タイムアウトしてもサーバ側で永続化されるため、写真一覧には間もなく出る。
    const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
    const maxAttempts = 20; // 約2秒間隔 × 20 ≒ 40秒
    for (let i = 0; i < maxAttempts; i++) {
      if (!isCurrent()) return; // 別の写真が開始/画面を離れたら古いポーリングは打ち切る
      let latest: NurseryInfo | null = null;
      try {
        latest = await getInfoById(created.id);
      } catch (e) {
        // 取得失敗は一時的なものとして次の試行へ
        console.warn('Polling draft status failed, retrying', e);
      }
      if (latest && latest.registration_state === 'registered') {
        const hasBody = !!(latest.content && latest.content.trim());
        applyIfCurrent(() => {
          setSavedDraft((prev) => (prev && prev.id === latest!.id ? latest! : prev));
          // 本文が無い＝OCR/enrich で実テキストが得られず仮タイトルのみ (SOT-1241)
          setEnrichFailed(!hasBody);
        });
        return;
      }
      await sleep(2000);
    }
  };

  const busy = phase === 'saving';

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <RegisterMenu />
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('create.autoTitle')}</h1>

      <div className="bg-surface shadow-md rounded-lg p-6 space-y-4">
        {phase === 'confirm' && previewUrl ? (
          <div className="border border-brand bg-brand-soft rounded-lg p-6 space-y-4">
            <h2 className="text-base font-semibold text-foreground text-center">
              {t('create.confirmHeading')}
            </h2>
            <div className="flex justify-center">
              <img
                src={previewUrl}
                alt={t('create.confirmImageAlt')}
                className="max-h-72 w-auto rounded-md border border-border shadow-sm"
              />
            </div>
            <div className="flex flex-col sm:flex-row gap-3 justify-center pt-1">
              <button
                type="button"
                onClick={() => pendingFile && startUpload(pendingFile)}
                className="px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-md shadow-sm hover:bg-brand-strong"
              >
                {t('create.confirmRegister')}
              </button>
              <button
                type="button"
                onClick={handleRetake}
                className="px-5 py-2.5 bg-surface text-foreground text-sm font-medium border border-border rounded-md hover:bg-surface-muted"
              >
                {t('create.confirmRetake')}
              </button>
            </div>
          </div>
        ) : phase === 'done' && savedDraft ? (
          <div className="border border-green-300 bg-green-50 rounded-lg p-6 space-y-4">
            <div className="flex items-center justify-center gap-2 text-green-700">
              <svg className="h-6 w-6" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span className="text-lg font-semibold">{t('create.autoSavedTitle')}</span>
            </div>
            <p className="text-sm text-foreground text-center">
              {enrichFailed ? t('create.autoSavedNoText') : t('create.autoSavedDesc')}
            </p>
            {/* SOT-1354: 生成されたタスク等は仮登録に出る。確認を促し、時間がかかることを説明する。 */}
            <p className="text-xs text-muted-foreground text-center">{t('create.autoSavedDraftHint')}</p>
            {savedDraft.title && (
              <p className="text-sm font-medium text-foreground truncate text-center">「{savedDraft.title}」</p>
            )}
            {savedDraft.content && (
              <div className="text-left bg-surface border border-border rounded-md p-3">
                <p className="text-xs font-medium text-muted-foreground mb-1">{t('create.autoSavedBodyHeading')}</p>
                <p className="text-sm text-foreground whitespace-pre-wrap line-clamp-6">{savedDraft.content}</p>
              </div>
            )}
            <div className="flex flex-col sm:flex-row gap-3 justify-center pt-2">
              <button
                type="button"
                onClick={() => navigate('/registered')}
                className="px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-md shadow-sm hover:bg-brand-strong"
              >
                {t('create.autoOpenDrafts')}
              </button>
              {/* SOT-1354: 仮登録(生成されたタスク等)の確認導線。 */}
              <button
                type="button"
                onClick={() => navigate('/drafts')}
                className="px-5 py-2.5 bg-surface text-foreground text-sm font-medium border border-border rounded-md hover:bg-surface-muted"
              >
                {t('create.autoOpenDraftCheck')}
              </button>
              <button
                type="button"
                onClick={resetForAnother}
                className="px-5 py-2.5 bg-surface text-foreground text-sm font-medium border border-border rounded-md hover:bg-surface-muted"
              >
                {t('create.autoUploadAnother')}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="border border-dashed border-brand bg-brand-soft rounded-lg p-6 text-center">
              <p className="text-sm text-foreground">{t('create.autoDesc')}</p>
              <input
                type="file"
                accept="image/*"
                ref={photoInputRef}
                onChange={handlePhotoSelect}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => photoInputRef.current?.click()}
                disabled={busy}
                className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-md shadow-sm hover:bg-brand-strong disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {phase === 'saving' ? (
                  <>
                    <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    {t('create.autoExtracting')}
                  </>
                ) : (
                  t('create.photoButton')
                )}
              </button>
              {extractError && (
                <p className="mt-3 text-sm text-red-600">{extractError}</p>
              )}
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={() => navigate(-1)}
                disabled={busy}
                className="px-4 py-2 text-sm font-medium text-foreground bg-surface border border-border rounded-md hover:bg-surface-muted disabled:opacity-50"
              >
                {t('create.cancel')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default AutoRegisterPage;
