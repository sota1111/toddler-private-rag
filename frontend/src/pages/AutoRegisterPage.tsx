import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { extractInfoDraft, createInfo, updateInfo, uploadAttachment } from '../api';
import type { NurseryInfo, NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { compressImageFile } from '../utils/imageCompression';
import { INFO_TYPES } from './infoFormOptions';
import RegisterMenu from '../components/RegisterMenu';

// 自動登録 = データ登録 (SOT-1052 / SOT-1113)
// 写真を選ぶとOCRで内容を読み取り、仮登録(draft)として永続化する。
// アップ完了後はその場で完了表示し、登録ページ(仮登録一覧)から本登録できる。
type Phase = 'idle' | 'saving' | 'enriching' | 'done';

const AutoRegisterPage: React.FC = () => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const photoInputRef = useRef<HTMLInputElement>(null);
  // 'idle' 入力待ち / 'saving' 仮登録保存中 / 'enriching' 文字起こし整理中 / 'done' 完了
  const [phase, setPhase] = useState<Phase>('idle');
  const [extractError, setExtractError] = useState<string | null>(null);
  const [savedDraft, setSavedDraft] = useState<NurseryInfo | null>(null);
  // 文字起こし/整理(enrich)に失敗したか（写真は保存済み）
  const [enrichFailed, setEnrichFailed] = useState(false);

  const resetForAnother = () => {
    setSavedDraft(null);
    setExtractError(null);
    setEnrichFailed(false);
    setPhase('idle');
  };

  const handlePhotoSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // input をリセットして同じファイルでも再選択できるようにする
    if (photoInputRef.current) photoInputRef.current.value = '';
    if (!file) return;

    setExtractError(null);
    setSavedDraft(null);
    setEnrichFailed(false);
    setPhase('saving');

    // アップロード前に圧縮・JPEG変換し、OCR・添付ともに変換後ファイルのみを使う（生データは保持しない）
    // 圧縮は失敗しても元ファイルにフォールバックするため throw しない。
    const processed = await compressImageFile(file);

    // SOT-1175: 「画像アップ完了をトリガーに画像変換と仮登録を始める」。
    // 重い画像変換(OCR/AI抽出)を待たずに、まず最小限の仮登録(draft)と写真添付を保存する。
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
        // SOT-1272: 文字起こし(enrich)が完了するまでは仮登録一覧に出さない。
        // まず非表示の処理中状態(processing)で保存し、enrich 完了時に draft へ昇格する。
        // 通常一覧/仮登録一覧の既存フィルタは draft/registered 以外を除外するため、
        // processing のレコードはどこにも表示されない (SOT-1113)。
        registration_state: 'processing',
      };

      // 仮登録を保存し、写真を添付する（ここまで成功＝データは失われない）
      created = await createInfo(initial);
      await uploadAttachment(created.id, processed);
      setSavedDraft(created);
    } catch (error) {
      console.error('Failed to save draft/photo on upload', error);
      setExtractError(t('create.autoSaveFail'));
      setPhase('idle');
      return;
    }

    // SOT-1214: 文字起こしを整理して仮登録本文へ反映するまで「整理中」を表示し、
    // 反映が完了してから完了カードを出す（完了時点で /drafts に本文が表示される）。
    // 抽出/補完は best-effort: 失敗しても保存済みのドラフトは破棄せず、失敗をユーザーに伝える。
    setPhase('enriching');
    // SOT-1241: 文字起こしが空/失敗のとき draft が「（タイトルなし）種別:資料」のまま
    // 写真だけ残るのを防ぐ。識別できる仮タイトル（当日日付付き）を付与し手入力を促す。
    const fallbackTitle = `${t('create.autoFallbackTitle')}（${new Date().toISOString().slice(0, 10)}）`;
    try {
      const draft = await extractInfoDraft(processed);

      // 文字起こし(OCR)で実テキストが得られたか。空なら補完せずフォールバック扱い。
      const hasText = (draft.raw_text || '').trim().length > 0;
      if (!hasText) {
        // 文字起こしで何も得られなかった: 識別できる仮タイトルを付与し手入力を促す。
        // SOT-1272: ここで処理完了なので draft へ昇格し、仮登録一覧に表示する。
        const updated = await updateInfo(created.id, { title: fallbackTitle, registration_state: 'draft' });
        setSavedDraft((prev) => (prev && prev.id === updated.id ? updated : prev));
        setEnrichFailed(true);
      } else {
        // 5カテゴリ抽出 (SOT-1092): 持ち物→items、注意事項→memo を補完プリフィル。
        const cats = draft.categories;
        const items = draft.items || (cats?.belongings?.length ? cats.belongings.join(', ') : '');
        const memo = cats?.notes?.length ? cats.notes.join('\n') : '';

        const enrichment: Partial<NurseryInfoCreate> = {
          title: draft.title || fallbackTitle,
          // 推定種別が選択肢に存在する場合のみ採用
          info_type: INFO_TYPES.includes(draft.info_type) ? draft.info_type : '資料',
          content: draft.content || '',
          date: draft.date || '',
          items,
          memo,
          // SOT-1272: enrich 完了。draft へ昇格して仮登録一覧に表示する。
          registration_state: 'draft',
        };

        const updated = await updateInfo(created.id, enrichment);
        // 補完後の内容に差し替える（別の写真を開始済みなら触らない）
        setSavedDraft((prev) => (prev && prev.id === updated.id ? updated : prev));
      }
    } catch (error) {
      // 抽出/補完は任意。失敗してもアップ済みのドラフトはそのまま使える。
      // 失敗時も仮タイトルだけは付与して /drafts で識別できるようにする (SOT-1241)。
      console.warn('Draft enrichment from OCR/AI failed (draft already saved)', error);
      try {
        // SOT-1272: 失敗しても処理は終わったので draft へ昇格し、仮登録一覧に表示する。
        const updated = await updateInfo(created.id, { title: fallbackTitle, registration_state: 'draft' });
        setSavedDraft((prev) => (prev && prev.id === updated.id ? updated : prev));
      } catch (e2) {
        console.warn('Fallback title update also failed', e2);
      }
      setEnrichFailed(true);
    } finally {
      setPhase('done');
    }
  };

  const busy = phase === 'saving' || phase === 'enriching';

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <RegisterMenu />
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('create.autoTitle')}</h1>

      <div className="bg-surface shadow-md rounded-lg p-6 space-y-4">
        {phase === 'enriching' ? (
          <div className="border border-brand bg-brand-soft rounded-lg p-6 text-center space-y-3">
            <div className="flex items-center justify-center gap-2 text-brand-strong">
              <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden>
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-base font-semibold">{t('create.autoEnriching')}</span>
            </div>
            <p className="text-sm text-foreground">{t('create.autoSavedDesc')}</p>
            <p className="text-sm text-muted-foreground">{t('create.autoEnrichingLeaveOk')}</p>
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
                onClick={() => navigate('/drafts')}
                className="px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-md shadow-sm hover:bg-brand-strong"
              >
                {t('create.autoOpenDrafts')}
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
