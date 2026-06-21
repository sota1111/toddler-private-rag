// 画像をアップロード前にクライアント側で圧縮・形式変換するユーティリティ (SOT-1009)
//
// 目的:
// - 大きな写真を画像認識に十分なサイズまで縮小してからアップロードする
// - 認識しやすい形式 (JPEG) に変換して保存する
// - 元の生データはアップロード/保持しない（変換後ファイルのみを保持する）

// 認識に十分な最長辺の上限（px）。これ以上大きい画像のみ縮小する。
export const MAX_IMAGE_DIMENSION = 1600;
// JPEG 書き出し品質（0-1）。OCR/画像認識に十分かつ容量を抑えるバランス。
export const IMAGE_QUALITY = 0.85;

// canvas 経由で再エンコードできるラスター画像形式のみ対象にする。
// （PDF などはそのまま通す）
const COMPRESSIBLE_TYPE = /^image\/(jpe?g|png|webp|bmp|gif)$/i;

const isCompressibleImage = (file: File): boolean =>
  file.type.startsWith('image/') && COMPRESSIBLE_TYPE.test(file.type);

// 元のファイル名の拡張子を .jpg に置き換える
const toJpegFilename = (name: string): string => {
  const base = name.replace(/\.[^./\\]+$/, '');
  return `${base || 'image'}.jpg`;
};

const loadImageElement = (file: File): Promise<HTMLImageElement> =>
  new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Failed to load image'));
    };
    img.src = url;
  });

const canvasToJpegBlob = (canvas: HTMLCanvasElement): Promise<Blob> =>
  new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error('Failed to encode image'));
      },
      'image/jpeg',
      IMAGE_QUALITY,
    );
  });

/**
 * 画像ファイルを「認識に十分なサイズ」へ縮小し、JPEG へ変換した新しい File を返す。
 * - 画像でないファイル（PDF など）はそのまま返す
 * - 失敗した場合は元ファイルを返す（ユーザー操作を絶対に止めない）
 */
export async function compressImageFile(file: File): Promise<File> {
  if (!isCompressibleImage(file)) {
    return file;
  }

  try {
    const img = await loadImageElement(file);
    const { naturalWidth: width, naturalHeight: height } = img;
    if (!width || !height) return file;

    // 最長辺が上限を超える場合のみ縮小（拡大はしない）
    const scale = Math.min(1, MAX_IMAGE_DIMENSION / Math.max(width, height));
    const targetW = Math.max(1, Math.round(width * scale));
    const targetH = Math.max(1, Math.round(height * scale));

    const canvas = document.createElement('canvas');
    canvas.width = targetW;
    canvas.height = targetH;
    const ctx = canvas.getContext('2d');
    if (!ctx) return file;

    // JPEG は透過を持てないため白背景で塗りつぶす
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, targetW, targetH);
    ctx.drawImage(img, 0, 0, targetW, targetH);

    const blob = await canvasToJpegBlob(canvas);

    // 変換後の方が大きく、かつ縮小もしていない（=既に小さい JPEG）場合は元を使う
    if (blob.size >= file.size && scale === 1 && file.type === 'image/jpeg') {
      return file;
    }

    return new File([blob], toJpegFilename(file.name), {
      type: 'image/jpeg',
      lastModified: Date.now(),
    });
  } catch {
    // どんな失敗でも元ファイルにフォールバック
    return file;
  }
}

/** 複数ファイルをまとめて圧縮（画像のみ変換、その他はそのまま） */
export async function compressImageFiles(files: File[]): Promise<File[]> {
  return Promise.all(files.map((f) => compressImageFile(f)));
}
