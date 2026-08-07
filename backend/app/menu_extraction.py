"""献立（給食メニュー）表を日付ごとに構造化分解する（menu-calendar 機能）。

アップロードされた画像/PDF が「献立表」と判定されたとき、Gemini vision で表を
**日付ごと**の構造化レコードに分解する。結果は登録写真レコード（nursery_info）の
``menu_json`` に保存され、カレンダー画面の「献立」モードから参照される。予定/タスク
レコード（event_date 付き）は一切作らないため、タスク一覧・予定一覧には出ない。

設計（SIGNATE 実証手順の移植）:
  1. 画像全体を一発で Gemini に投げて ``MenuDay[]`` を得る（安価）。
  2. 完全性ゲート: 給食が空 / 主要食材が空 / 栄養価欠落の日付を検出。
  3. フォールバック: 画像を重なり付きの帯に分割し、疎な日付が残る間だけ帯を再抽出し、
     日付で max-completeness マージする（numpy 非依存・PIL のみ）。
  4. 総呼び出し数は ``MENU_EXTRACT_MAX_CALLS`` で上限を設ける。

すべて best-effort。フラグ OFF（既定）や失敗時は ``None`` を返し、既存パイプラインを
一切変えない（byte-identical）。重い依存（PIL / pdf2image / google-genai）はすべて
遅延 import なので、本モジュールの import は常に安全・軽量。
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# --- 発火判定に使うキーワード / しきい値 -----------------------------------------
_MENU_KEYWORDS = ("献立", "給食")
_COLOR_HEADERS = ("エネルギーのもとになる", "体をつくる", "調子を整える", "主要食材", "体の調子")
_MIN_DAY_TOKENS = 8  # 表とみなす最小の「日付らしいトークン」数

# 主要食材の3色（＋その他）
_ING_KEYS = ("red", "yellow", "green", "other")


def menu_extraction_enabled() -> bool:
    """献立の日付分解を実行するか。既定 OFF（未設定/偽値で無効）。"""
    return os.getenv("MENU_TABLE_EXTRACTION_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _max_calls() -> int:
    try:
        return max(1, int(os.getenv("MENU_EXTRACT_MAX_CALLS", "40")))
    except (TypeError, ValueError):
        return 40


def detect_menu_table(text: str) -> bool:
    """OCR テキストが「献立**表**」かを二段で判定する。

    献立だより（文章）で重い分解を走らせないため、キーワード（献立/給食）に加えて
    「表らしさ」（栄養価 kcal 見出し or 3色食品群見出し＋多数の日付トークン）を要求する。
    """
    if not text:
        return False
    if not any(k in text for k in _MENU_KEYWORDS):
        return False
    has_kcal = "kcal" in text.lower()
    has_color = any(k in text for k in _COLOR_HEADERS)
    day_tokens = len(re.findall(r"(?<!\d)\d{1,2}(?=\s*[日\n])", text))
    return has_kcal or (has_color and day_tokens >= _MIN_DAY_TOKENS)


# --- 年月の解決 -------------------------------------------------------------------
def _resolve_year_month(
    ocr_text: str, issue_year: Optional[int], issue_month: Optional[int]
) -> tuple[int, int]:
    """献立の対象年月を決める。月はタイトル「N月の献立」を優先、無ければ発行月/今月。"""
    import datetime

    month = None
    m = re.search(r"(\d{1,2})\s*月.{0,4}献立", ocr_text or "")
    if not m:
        m = re.search(r"(\d{1,2})\s*月", ocr_text or "")
    if m:
        cand = int(m.group(1))
        if 1 <= cand <= 12:
            month = cand
    if month is None:
        month = issue_month or datetime.date.today().month
    year = issue_year or datetime.date.today().year
    return year, month


# --- ページ画像 / 帯の生成（PIL のみ）--------------------------------------------
def _load_page_images(file_path: Path, mime_type: str) -> List[bytes]:
    """OCR 対象を JPEG バイト列のリストにする（画像=1枚、PDF=ページごと）。"""
    if mime_type == "application/pdf":
        try:
            from pdf2image import convert_from_path
        except ImportError:  # pragma: no cover - 環境依存
            logger.warning("pdf2image not installed; skipping menu extraction for PDF")
            return []
        out: List[bytes] = []
        for page in convert_from_path(str(file_path)):
            buf = io.BytesIO()
            page.convert("RGB").save(buf, format="JPEG", quality=92)
            out.append(buf.getvalue())
        return out
    if mime_type.startswith("image/"):
        try:
            return [Path(file_path).read_bytes()]
        except OSError:  # pragma: no cover
            return []
    return []


def _band_images(image_bytes: bytes, bands: int, overlap: float) -> List[bytes]:
    """画像を全幅のまま縦方向へ重なり付き分割し、各帯の先頭に列見出しを再掲する。

    見出し再掲により、下部の帯でも「給食/主要食材/栄養価」の列意味が失われない。
    numpy 非依存（PIL のみ）。
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return []
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # pragma: no cover - 壊れた画像
        return []
    w, h = im.size
    header_h = max(1, int(h * 0.08))
    header = im.crop((0, 0, w, header_h))
    seg = h / bands
    out: List[bytes] = []
    for i in range(bands):
        top = max(0, int(i * seg - overlap * seg))
        bot = min(h, int((i + 1) * seg + overlap * seg))
        body = im.crop((0, top, w, bot))
        canvas = Image.new("RGB", (w, header_h + body.height), "white")
        canvas.paste(header, (0, 0))
        canvas.paste(body, (0, header_h))
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=92)
        out.append(buf.getvalue())
    return out


# --- Gemini 呼び出し（テストはこの関数を monkeypatch する）------------------------
_MENU_PROMPT = (
    "この画像は保育園の『献立表』の一部です。表に実在する日付の行だけを、日付ごとに1件、"
    "JSON配列で正確に抽出してください。存在しない日付（空白行）は出力しない。"
    "各セルの改行区切り項目は配列要素に分解。数値(kcal・g)は画像の値を正確に。"
    "読み取れない箇所は空配列/空。推測や創作は禁止。"
    "主要食材の4列は 赤(体をつくる)=red・黄(エネルギー)=yellow・緑(調子を整える)=green・その他=other。"
    "栄養価は3歳未満=under3・3歳以上=over3 で、各 energy_kcal/protein_g/fat_g。列順は"
    "エネルギー→たんぱく質→脂質。"
    'JSONのみ返す。要素の形: {"date":整数(日),"weekday":"曜日",'
    '"morning_snack":[],"lunch":[],"afternoon_snack":[],'
    '"main_ingredients":{"red":[],"yellow":[],"green":[],"other":[]},'
    '"nutrition":{"under3":{"energy_kcal":0,"protein_g":0,"fat_g":0},'
    '"over3":{"energy_kcal":0,"protein_g":0,"fat_g":0}}}'
)


def _call_gemini_menu(image_bytes: bytes, mime_type: str) -> List[dict]:
    """1画像を Gemini vision に投げ、日付レコードの生 list を返す。失敗時は空 list。"""
    from .ai_client import get_genai_client, get_model_name, with_retry

    model = get_model_name()
    config = None
    try:
        from google.genai import types

        kwargs = dict(
            temperature=0,
            max_output_tokens=8192,
            response_mime_type="application/json",
        )
        # flash 系は thinking を無効化して出力枠が思考で食い潰されるのを防ぐ。
        # pro 系は thinking_budget=0 が拒否されるため設定しない。
        if "pro" not in model.lower():
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        config = types.GenerateContentConfig(**kwargs)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    except Exception:  # pragma: no cover - SDK 差異
        image_part = None

    try:
        client = get_genai_client()

        def _generate():
            if image_part is not None:
                return client.models.generate_content(
                    model=model, contents=[image_part, _MENU_PROMPT], config=config
                )
            # フォールバック: PIL Image で渡す
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes))
            return client.models.generate_content(
                model=model, contents=[_MENU_PROMPT, img]
            )

        response = with_retry(_generate)
        text = (getattr(response, "text", "") or "").strip()
        return _parse_rows(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("Gemini menu extraction call failed: %s", type(e).__name__)
        return []


def _parse_rows(text: str) -> List[dict]:
    """モデル出力（JSON 配列、まれに ```json フェンス付き）を list[dict] に整える。"""
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


# --- 完全性・マージ ---------------------------------------------------------------
def _completeness(day: dict) -> int:
    n = len(day.get("lunch") or []) * 2
    for k in ("morning_snack", "afternoon_snack"):
        n += len(day.get(k) or [])
    mi = day.get("main_ingredients") or {}
    for k in _ING_KEYS:
        n += len(mi.get(k) or [])
    nu = day.get("nutrition") or {}
    for grp in ("under3", "over3"):
        n += sum(1 for v in (nu.get(grp) or {}).values() if v not in (None, "", 0))
    return n


def _is_sparse(day: dict) -> bool:
    mi = day.get("main_ingredients") or {}
    ing = sum(len(mi.get(k) or []) for k in _ING_KEYS)
    o3 = (day.get("nutrition") or {}).get("over3") or {}
    return (not (day.get("lunch") or [])) or ing == 0 or not o3.get("energy_kcal")


def _day_num(day: dict) -> Optional[int]:
    raw = day.get("date")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= 31 else None
    if isinstance(raw, str):
        m = re.search(r"\d{1,2}", raw)
        if m:
            v = int(m.group())
            return v if 1 <= v <= 31 else None
    return None


def _merge(best: dict, rows: List[dict]) -> None:
    """rows を best（day-of-month → record）へ max-completeness でマージする（in place）。"""
    for r in rows:
        dt = _day_num(r)
        if dt is None:
            continue
        if dt not in best or _completeness(r) >= _completeness(best[dt]):
            r = dict(r)
            r["date"] = dt
            best[dt] = r


def _to_iso_days(best: dict, year: int, month: int) -> List[dict]:
    """day-of-month キーの record を ISO 日付付きの MenuDay dict 群へ変換する。"""
    import calendar

    _, last = calendar.monthrange(year, month)
    out: List[dict] = []
    for dt in sorted(best):
        if dt > last:
            continue
        rec = dict(best[dt])
        rec["date"] = f"{year:04d}-{month:02d}-{dt:02d}"
        rec.setdefault("weekday", "")
        for k in ("morning_snack", "lunch", "afternoon_snack"):
            rec.setdefault(k, [])
        mi = rec.get("main_ingredients") or {}
        rec["main_ingredients"] = {k: mi.get(k) or [] for k in _ING_KEYS}
        rec.setdefault("nutrition", {})
        out.append(rec)
    return out


def extract_menu_by_date(
    file_path,
    mime_type: str,
    ocr_text: str,
    *,
    issue_year: Optional[int] = None,
    issue_month: Optional[int] = None,
) -> Optional[dict]:
    """献立画像/PDF を日付ごとに分解し ``{"month": "YYYY-MM", "days": [MenuDay...]}`` を返す。

    best-effort。抽出ゼロ/失敗時は ``None``。呼び出し側はフラグと ``detect_menu_table``
    で既に守っている前提だが、本関数単体でも安全に失敗する。
    """
    year, month = _resolve_year_month(ocr_text, issue_year, issue_month)
    pages = _load_page_images(Path(file_path), mime_type)
    if not pages:
        return None

    calls = 0
    limit = _max_calls()
    best: dict = {}
    for page in pages:
        # パス1: ページ全体を一発抽出。
        if calls >= limit:
            break
        _merge(best, _call_gemini_menu(page, "image/jpeg"))
        calls += 1

        # パス2: 疎な日付が残る/密な表なら、重なり付きの帯で精密抽出してマージ。
        sparse_or_thin = (not best) or any(_is_sparse(d) for d in best.values())
        if sparse_or_thin and calls < limit:
            for band in _band_images(page, bands=6, overlap=0.5):
                if calls >= limit:
                    break
                _merge(best, _call_gemini_menu(band, "image/jpeg"))
                calls += 1

    days = _to_iso_days(best, year, month)
    if not days:
        return None
    logger.info(
        "[menu] extracted %d day(s) for %04d-%02d in %d Gemini call(s)",
        len(days),
        year,
        month,
        calls,
    )
    return {"month": f"{year:04d}-{month:02d}", "days": days}
