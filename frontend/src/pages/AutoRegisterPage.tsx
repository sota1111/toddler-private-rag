import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { extractInfoDraft, createInfo, uploadAttachment } from '../api';
import type { NurseryInfo, NurseryInfoCreate } from '../types';
import { useI18n } from '../i18n/useI18n';
import { compressImageFile } from '../utils/imageCompression';
import { INFO_TYPES } from './infoFormOptions';
import RegisterMenu from '../components/RegisterMenu';

// 自動登録 = データ登録 (SOT-1052 / SOT-1113)
// 写真を選ぶとOCRで内容を読み取り、仮登録(draft)として永続化する。
// アップ完了後はその場で完了表示し、登録ページ(仮登録一覧)から本登録できる。
const AutoRegisterPage: React.FC = () => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const photoInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [savedDraft, setSavedDraft] = useState<NurseryInfo | null>(null);

  const handlePhotoSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // input をリセットして同じファイルでも再選択できるようにする
    if (photoInputRef.current) photoInputRef.current.value = '';
    if (!file) return;

    setExtractError(null);
    setSavedDraft(null);
    setIsUploading(true);

    try {
      // アップロード前に圧縮・JPEG変換し、OCR・添付ともに変換後ファイルのみを使う（生データは保持しない）
      const processed = await compressImageFile(file);
      const draft = await extractInfoDraft(processed);

      // 5カテゴリ抽出 (SOT-1092): 持ち物→items、注意事項→memo を補完プリフィル。
      const cats = draft.categories;
      const items = draft.items || (cats?.belongings?.length ? cats.belongings.join(', ') : '');
      const memo = cats?.notes?.length ? cats.notes.join('\n') : '';

      const data: NurseryInfoCreate = {
        title: draft.title || '',
        // 推定種別が選択肢に存在する場合のみ採用
        info_type: INFO_TYPES.includes(draft.info_type) ? draft.info_type : '資料',
        content: draft.content || '',
        date: draft.date || '',
        event_date: '',
        due_date: '',
        items,
        status: '未対応',
        priority: '普通',
        tags: '',
        memo,
        // 仮登録として永続化する (SOT-1113)
        registration_state: 'draft',
      };

      // 仮登録を保存し、写真を添付する
      const created = await createInfo(data);
      await uploadAttachment(created.id, processed);
      setSavedDraft(created);
    } catch (error) {
      console.error('Failed to register draft from photo', error);
      setExtractError(t('create.autoSaveFail'));
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="w-full lg:max-w-3xl lg:mx-auto pb-12">
      <RegisterMenu />
      <h1 className="text-2xl font-bold mb-6 text-foreground">{t('create.autoTitle')}</h1>

      <div className="bg-surface shadow-md rounded-lg p-6 space-y-4">
        {savedDraft ? (
          <div className="border border-green-300 bg-green-50 rounded-lg p-6 text-center space-y-4">
            <div className="flex items-center justify-center gap-2 text-green-700">
              <svg className="h-6 w-6" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span className="text-lg font-semibold">{t('create.autoSavedTitle')}</span>
            </div>
            <p className="text-sm text-foreground">{t('create.autoSavedDesc')}</p>
            {savedDraft.title && (
              <p className="text-sm font-medium text-foreground truncate">「{savedDraft.title}」</p>
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
                onClick={() => setSavedDraft(null)}
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
                disabled={isUploading}
                className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-md shadow-sm hover:bg-brand-strong disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isUploading ? (
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
                disabled={isUploading}
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
