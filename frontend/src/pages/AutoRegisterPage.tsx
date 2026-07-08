import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createInfo, uploadAttachmentSmart, getInfoById, getChildren, deleteInfo } from '../api';
import type { Child, NurseryInfo, NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { useSettings } from '../settings/useSettings';
import { compressImageFile } from '../utils/imageCompression';
import RegisterMenu from '../components/RegisterMenu';

// 自動登録 = データ登録 (SOT-1052 / SOT-1113)
// 写真を選ぶとOCRで内容を読み取り、仮登録(draft)として永続化する。
// SOT-1293: enrich(JSON生成)→Firestore永続化→draft昇格はサーバ側で行う。ブラウザは
// createInfo(processing)+写真アップのみを行い、以降はサーバ任せ（タブを閉じても仮登録に出る）。
// 完了表示のため、サーバ側の draft 昇格をポーリングで待って結果を反映する。
// SOT-1498: 複数枚の写真を同時に選択し、まとめてアップロードできる。各写真はそれぞれ
// createInfo(processing)+写真アップされ、サーバ側で個別に OCR/enrich が進む。
type Phase = 'idle' | 'confirm' | 'saving' | 'done';

// SOT-1593: 選択したファイルが PDF かどうか（MIME か拡張子で判定）。
const isPdfFile = (file?: File | null): boolean =>
  file?.type === 'application/pdf' || /\.pdf$/i.test(file?.name ?? '');

const AutoRegisterPage: React.FC = () => {
  const { t, lang } = useI18n();
  // SOT-1405: 設定済み市町村を写真アップロードに渡し、自動締切調査の市町村DLリンク付与に使う。
  const { municipality } = useSettings();
  const navigate = useNavigate();
  const photoInputRef = useRef<HTMLInputElement>(null);
  // SOT-1289: 文字起こし整理中でも次の写真を追加できる。並行アップロード時、
  // 進行中だった前のアップロードの setState（特に finally の done 昇格）が
  // 新しいアップロードの画面状態を上書きしないよう、世代カウンタで最新のみ反映する。
  const uploadSeqRef = useRef(0);
  // SOT-1322: 「写真をアップしています…」表示を短くするため、画像圧縮(端末側で数秒かかる)を
  // 確認フェーズ(プレビュー表示中)で先行実行しておく。圧縮はキャンセル不可なので Promise を
  // 保持し、アップロード確定時に最新のものを await して再利用する(間に合っていなければ従来同様に待つ)。
  // SOT-1498: 複数枚選択に対応するため、選択したファイルと同じ順序の Promise 配列で保持する。
  const compressedRef = useRef<Promise<File>[] | null>(null);
  // 'idle' 入力待ち / 'confirm' 写真確認待ち / 'saving' 仮登録保存中 / 'done' 完了
  // SOT-1322: アップロード成功＝写真は保存済みなので即 'done'。整理(OCR/enrich)はサーバ側の
  // バックグラウンドで進み、完了したら done カードのタイトル/本文をバックグラウンドで更新する。
  const [phase, setPhase] = useState<Phase>('idle');
  const [extractError, setExtractError] = useState<string | null>(null);
  const [savedDraft, setSavedDraft] = useState<NurseryInfo | null>(null);
  // SOT-1498: このバッチで保存に成功した枚数・失敗した枚数（複数枚の完了表示に使う）
  const [savedCount, setSavedCount] = useState(0);
  const [failedCount, setFailedCount] = useState(0);
  // 文字起こし/整理(enrich)に失敗したか（写真は保存済み）
  const [enrichFailed, setEnrichFailed] = useState(false);
  // SOT-1288: アップ前に「この写真で良いか」を確認する。確定するまでサーバ保存しない。
  // SOT-1498: 複数枚選択に対応するため配列で保持する。
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);
  // SOT-1368: 紐づけるお子さま。確認フェーズで選択し、初期 createInfo に付与する。
  const [children, setChildren] = useState<Child[]>([]);
  const [childId, setChildId] = useState('');

  useEffect(() => {
    getChildren()
      .then(setChildren)
      .catch(() => {
        /* お子さま一覧の取得失敗は致命的でない。紐付けなしで続行する。 */
      });
  }, []);

  // プレビュー用の objectURL をすべて破棄する（不要になった時点で必ず呼ぶ）
  const clearPreview = () => {
    setPreviewUrls((prev) => {
      prev.forEach((url) => URL.revokeObjectURL(url));
      return [];
    });
    setPendingFiles([]);
  };

  // アンマウント時に objectURL を解放する
  useEffect(() => {
    return () => {
      previewUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [previewUrls]);

  const resetForAnother = () => {
    // SOT-1322: 進行中のバックグラウンドポーリングを無効化し、idle 画面を上書きさせない
    uploadSeqRef.current += 1;
    clearPreview();
    // SOT-1322: 先行圧縮結果をクリア
    compressedRef.current = null;
    setSavedDraft(null);
    setSavedCount(0);
    setFailedCount(0);
    setExtractError(null);
    setEnrichFailed(false);
    setPhase('idle');
  };

  // 写真を選択したら確認画面へ。まだアップロードは始めない (SOT-1288)。
  // SOT-1498: 複数枚選択に対応。選んだ全ファイルを確認画面に並べる。
  const handlePhotoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    // input をリセットして同じファイルでも再選択できるようにする
    if (photoInputRef.current) photoInputRef.current.value = '';
    if (files.length === 0) return;

    // SOT-1322: 進行中のバックグラウンドポーリングを無効化し、新しい写真の画面を上書きさせない
    uploadSeqRef.current += 1;
    setExtractError(null);
    setSavedDraft(null);
    setSavedCount(0);
    setFailedCount(0);
    setEnrichFailed(false);
    // 既存のプレビューがあれば破棄してから新しいものを保持する
    previewUrls.forEach((url) => URL.revokeObjectURL(url));
    setPendingFiles(files);
    setPreviewUrls(files.map((file) => URL.createObjectURL(file)));
    // SOT-1322: 確認中に画像圧縮を先行実行しておく(失敗時は元ファイルにフォールバックし throw しない)。
    // 古い圧縮結果を使わないよう、新しいファイル群の圧縮で必ず上書きする。
    compressedRef.current = files.map((file) => compressImageFile(file));
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

  // 確認画面で「登録」を押したときに初めてアップロード・仮登録を開始する。
  // SOT-1498: 選択した全ファイルをまとめてアップロードする。
  const startUpload = async (files: File[]) => {
    // SOT-1289: このアップロード(バッチ)の世代を採番。以降の画面状態(setState)更新は、
    // 自分が最新世代のときだけ反映する（保存処理 createInfo/uploadAttachment 自体は
    // 全写真分そのまま実行する）。
    const seq = ++uploadSeqRef.current;
    const isCurrent = () => uploadSeqRef.current === seq;
    const applyIfCurrent = (fn: () => void) => {
      if (isCurrent()) fn();
    };

    // 確認フェーズで先行実行した圧縮結果（ファイルと同じ順序）を取り出す。
    const compressedPromises = compressedRef.current ?? files.map((file) => compressImageFile(file));
    compressedRef.current = null;

    // プレビューはここで破棄してよい（保存処理は圧縮後ファイルを使う）
    clearPreview();
    setExtractError(null);
    setSavedDraft(null);
    setSavedCount(0);
    setFailedCount(0);
    setEnrichFailed(false);
    setPhase('saving');

    // SOT-1175: 「画像アップ完了をトリガーに画像変換と仮登録を始める」。
    // 各写真について、最小限の仮登録(processing)を作り写真を添付する。写真アップロードが
    // サーバ側 enrich→draft 昇格のトリガーになる。SOT-1498: 複数枚を並行で処理する。
    const results = await Promise.all(
      files.map(async (file, i) => {
        // アップロード前に圧縮・JPEG変換し、OCR・添付ともに変換後ファイルのみを使う（生データは保持しない）。
        // 圧縮は失敗しても元ファイルにフォールバックするため throw しない。
        const processed = await (compressedPromises[i] ?? compressImageFile(file));
        // SOT-1476: createInfo で作った processing 番兵の id を控える。写真アップロードが
        // 失敗した場合、この番兵だけがサーバに残り「文字起こし中」が仮登録画面に出たままに
        // なるため、失敗時に掃除(削除)する。
        let createdId: number | string | null = null;
        try {
          const initial: NurseryInfoCreate = {
            title: '',
            info_type: '資料',
            content: '',
            date: '',
            event_date: '',
            due_date: '',
            items: '',
            status: '未確認',
            priority: '普通',
            tags: '',
            memo: '',
            // SOT-1368: 選択したお子さまに紐付ける（未選択は紐付けなし）。
            child_id: childId || null,
            // SOT-1272/SOT-1293: enrich が完了するまでは仮登録一覧に出さない。
            // まず非表示の処理中状態(processing)で保存する。サーバ側の OCR background task が
            // enrich→draft 昇格まで行うため、ここで write を続ける必要はない。
            registration_state: 'processing',
          };

          // 仮登録を保存し、写真を添付する（ここまで成功＝データは失われない）。
          const created = await createInfo(initial);
          createdId = created.id;
          // SOT-1315: 設定言語(lang)を渡し、文字起こし後のタスク登録をその言語で生成させる。
          // SOT-1377: 画像本体は Cloud Run を経由せず GCS へ直接アップロードする(session方式)。
          await uploadAttachmentSmart(created.id, processed, lang, municipality);
          return { ok: true as const, created };
        } catch (error) {
          console.error('Failed to save draft/photo on upload', error);
          // SOT-1476: 写真アップロードが失敗すると、createInfo で作った processing 番兵だけが
          // サーバに残り、OCR トリガー(=アップロード)が発火しないため永久に processing のままになる。
          // 写真は保存されておらず失うデータは無いため、この番兵を掃除する。
          if (createdId !== null) {
            try {
              await deleteInfo(createdId);
            } catch (cleanupError) {
              console.warn('Failed to clean up processing draft after upload failure', cleanupError);
            }
          }
          return { ok: false as const };
        }
      }),
    );

    const succeeded = results.filter(
      (r): r is { ok: true; created: NurseryInfo } => r.ok,
    );
    const failed = results.length - succeeded.length;

    // すべて失敗した場合はエラーを表示して入力待ちに戻す（保存済みの写真はない）。
    if (succeeded.length === 0) {
      applyIfCurrent(() => {
        setExtractError(t('create.autoSaveFail'));
        setPhase('idle');
      });
      return;
    }

    // SOT-1322: アップロード成功＝写真はサーバ保存済み。整理(OCR/enrich)はサーバ側の
    // バックグラウンドで進むため、ユーザーを待たせず即「完了」表示にする。
    // SOT-1380 follow-up: 写真アップ直後だと仮登録画面に知らせるため、アップ時刻を記録する。
    try {
      sessionStorage.setItem('tpr.lastPhotoUploadAt', String(Date.now()));
    } catch {
      /* sessionStorage が使えなくても致命的ではない（表示の最適化のみ） */
    }

    applyIfCurrent(() => {
      setSavedCount(succeeded.length);
      setFailedCount(failed);
      // 1枚のときは従来どおり enrich 結果(タイトル/本文)を表示する。
      if (succeeded.length === 1) setSavedDraft(succeeded[0].created);
      setPhase('done');
    });

    // SOT-1293/SOT-1324: enrich(JSON生成)→Firestore永続化→登録昇格はサーバ側で進む。
    // SOT-1322: 1枚のときはバックグラウンドで登録昇格をポーリングし、完了したら完了カードの
    // タイトル/本文だけを更新する（待ち画面で足止めしない）。複数枚のときは個別の本文表示は
    // 行わず（仮登録一覧で確認できる）、ポーリングはしない。
    if (succeeded.length !== 1) return;
    const created = succeeded[0].created;
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
  const isMulti = previewUrls.length > 1;

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <RegisterMenu />
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('create.autoTitle')}</h1>

      <div className="bg-surface shadow-md rounded-lg p-6 space-y-4">
        {phase === 'confirm' && previewUrls.length > 0 ? (
          <div className="border border-brand bg-brand-soft rounded-lg p-6 space-y-4">
            <h2 className="text-base font-semibold text-foreground text-center">
              {isMulti
                ? t('create.confirmHeadingMulti', { count: previewUrls.length })
                : t('create.confirmHeading')}
            </h2>
            <div
              className={
                isMulti
                  ? 'grid grid-cols-3 sm:grid-cols-4 gap-2 justify-items-center'
                  : 'flex justify-center'
              }
            >
              {previewUrls.map((url, i) => {
                // PDF は <img> で表示できないため、アイコン + ファイル名のプレースホルダを出す (SOT-1593)。
                const file = pendingFiles[i];
                const isPdf = isPdfFile(file);
                if (isPdf) {
                  return (
                    <div
                      key={url}
                      className={
                        isMulti
                          ? 'h-24 w-24 flex flex-col items-center justify-center gap-1 rounded-md border border-border bg-surface shadow-sm p-1'
                          : 'h-72 w-56 flex flex-col items-center justify-center gap-2 rounded-md border border-border bg-surface shadow-sm p-4'
                      }
                    >
                      <svg
                        className={isMulti ? 'h-8 w-8 text-brand' : 'h-14 w-14 text-brand'}
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={1.5}
                        aria-hidden="true"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                        />
                      </svg>
                      <span
                        className={`text-center break-all text-muted-foreground ${isMulti ? 'text-[10px] leading-tight line-clamp-2' : 'text-xs'}`}
                        title={file?.name}
                      >
                        {file?.name ?? t('create.confirmPdfLabel')}
                      </span>
                    </div>
                  );
                }
                return (
                  <img
                    key={url}
                    src={url}
                    alt={`${t('create.confirmImageAlt')}${isMulti ? ` (${i + 1})` : ''}`}
                    className={
                      isMulti
                        ? 'h-24 w-24 object-cover rounded-md border border-border shadow-sm'
                        : 'max-h-72 w-auto rounded-md border border-border shadow-sm'
                    }
                  />
                );
              })}
            </div>
            {children.length > 0 && (
              <label className="block text-sm max-w-xs mx-auto w-full">
                <span className="mb-1 block font-medium text-foreground text-center">{t('child.fieldLabel')}</span>
                <select
                  value={childId}
                  onChange={(e) => setChildId(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-foreground"
                >
                  <option value="">{t('child.none')}</option>
                  {children.map((c) => (
                    <option key={c.id} value={String(c.id)}>{c.name}</option>
                  ))}
                </select>
              </label>
            )}
            <div className="flex flex-col sm:flex-row gap-3 justify-center pt-1">
              <button
                type="button"
                onClick={() => pendingFiles.length > 0 && startUpload(pendingFiles)}
                className="px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-md shadow-sm hover:bg-brand-strong"
              >
                {isMulti
                  ? t('create.confirmRegisterMulti', { count: pendingFiles.length })
                  : t('create.confirmRegister')}
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
            {failedCount > 0 && (
              <p className="text-sm text-red-600 text-center">
                {t('create.autoSavedPartialFail', { count: failedCount })}
              </p>
            )}
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
        ) : phase === 'done' && savedCount > 0 ? (
          // SOT-1498: 複数枚を保存したときの完了表示（個別の本文は仮登録一覧で確認）。
          <div className="border border-green-300 bg-green-50 rounded-lg p-6 space-y-4">
            <div className="flex items-center justify-center gap-2 text-green-700">
              <svg className="h-6 w-6" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span className="text-lg font-semibold">{t('create.autoSavedTitle')}</span>
            </div>
            <p className="text-sm text-foreground text-center">
              {t('create.autoSavedMultiDesc', { count: savedCount })}
            </p>
            {failedCount > 0 && (
              <p className="text-sm text-red-600 text-center">
                {t('create.autoSavedPartialFail', { count: failedCount })}
              </p>
            )}
            <p className="text-xs text-muted-foreground text-center">{t('create.autoSavedDraftHint')}</p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center pt-2">
              <button
                type="button"
                onClick={() => navigate('/registered')}
                className="px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-md shadow-sm hover:bg-brand-strong"
              >
                {t('create.autoOpenDrafts')}
              </button>
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
                accept="image/*,application/pdf,.pdf"
                multiple
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
