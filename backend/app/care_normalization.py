"""SOT-2730: アレルゲン別名辞書と配慮カテゴリのキーワード正規化（決定論・LLM非依存）。

後続のおたより照合エンジン（SOT-2733）が参照する「決定論的な土台」を提供する純関数群。
表記ゆれ（卵/たまご/玉子/エッグ …）を正規形（``egg`` …）へ集約し、照合の誤検出・取りこぼしの
制御点を1箇所に集める。ここには LLM 呼び出しも I/O も一切なく、同じ入力に対して常に同じ出力を返す。

設計方針:
- **正規形は英語スネークケースの安定キー**（``egg`` / ``animal_contact`` …）。DB へ保存される
  ``CareProfile.allergens`` / ``care_categories`` は自由記述文字列（SOT-2729）なので、照合層は
  保存値をこのモジュールで正規化してから突き合わせる想定。正規形キーは表示ラベルではなく識別子。
- **未知語は誤って正規化しない**。辞書に無い語は ``None``（別名解決）／空集合（テキスト走査）を返し、
  勝手に近い正規形へ寄せない。安全側（見落としより誤った断定を避ける）に倒すため。
- **NFKC + casefold + 記号除去** で表記ゆれを吸収してから辞書引きする（全角/半角・大文字/小文字・
  「・」「（）」「アレルギー」等の付随語を落とす）。辞書キーも同じ関数で正規化して構築するため、
  辞書へ人間可読な別名を書けば自動でマッチキーになる。
"""

from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional, Tuple

# --- 正規形（安定キー） ---------------------------------------------------------

# アレルゲン正規形。日本の食品表示法における特定原材料8品目（義務表示）＋
# 特定原材料に準ずるもの20品目（推奨表示）を対象にする。値は照合層で使う安定キー。
ALLERGEN_EGG = "egg"
ALLERGEN_MILK = "milk"
ALLERGEN_WHEAT = "wheat"
ALLERGEN_BUCKWHEAT = "buckwheat"
ALLERGEN_PEANUT = "peanut"
ALLERGEN_SHRIMP = "shrimp"
ALLERGEN_CRAB = "crab"
ALLERGEN_WALNUT = "walnut"

# MVP対象の配慮カテゴリ正規形（SOT-2728 Main Use Case 2 の初期3カテゴリ）。
CARE_ANIMAL_CONTACT = "animal_contact"
CARE_LOUD_NOISE = "loud_noise"
CARE_MOTION_SICKNESS = "motion_sickness"


def _canonical_key(term: str) -> str:
    """表記ゆれ吸収用の内部キーへ変換する（辞書構築・辞書引きの両方で使う共通関数）。

    NFKC で全角/半角・互換文字を統一し、casefold で大文字小文字を無視、空白と一部の区切り記号を
    落とす。これにより「エッグ」「ｴｯｸﾞ」「 Egg 」「たまご・卵」等が同じキーへ寄る。
    """
    if term is None:
        return ""
    # NFKC: 全角英数→半角、半角カナ→全角カナ、互換文字の正規化。
    normalized = unicodedata.normalize("NFKC", str(term))
    # 大文字小文字・一部の言語差を無視（ASCII の lower より頑健）。
    normalized = normalized.casefold()
    # 区切り・装飾記号や空白を除去（「卵（鶏卵）」「animal-contact」等を吸収）。
    stripped = []
    for ch in normalized:
        if ch.isspace():
            continue
        if ch in "・･-‐-—―_/／\\（）()[]【】「」『』、,.。:：;；":
            continue
        stripped.append(ch)
    return "".join(stripped)


def _build_alias_map(entries: Dict[str, Tuple[str, ...]]) -> Dict[str, str]:
    """{正規形: (別名…)} を {正規化キー: 正規形} の逆引き辞書へ展開する。

    正規形自身も別名として登録し、既に正規形が渡された場合も解決できるようにする。
    正規化キーの衝突（同じキーが別の正規形へ割り当たる）は辞書定義バグなので早期に気付けるよう
    ``ValueError`` を送出する。
    """
    lookup: Dict[str, str] = {}
    for canonical, aliases in entries.items():
        for surface in (canonical,) + tuple(aliases):
            key = _canonical_key(surface)
            if not key:
                continue
            existing = lookup.get(key)
            if existing is not None and existing != canonical:
                raise ValueError(
                    f"alias collision: {surface!r} -> {canonical!r} conflicts with {existing!r}"
                )
            lookup[key] = canonical
    return lookup


# --- アレルゲン別名辞書 ---------------------------------------------------------

# {正規形: (別名タプル)}。別名は人間可読なまま書けばよい（_canonical_key で正規化される）。
_ALLERGEN_ALIASES: Dict[str, Tuple[str, ...]] = {
    ALLERGEN_EGG: ("卵", "たまご", "タマゴ", "玉子", "鶏卵", "鶏卵（卵）", "エッグ", "egg", "eggs"),
    ALLERGEN_MILK: (
        "乳", "牛乳", "ミルク", "乳製品", "乳成分", "チーズ", "バター",
        "milk", "dairy", "cow milk",
    ),
    ALLERGEN_WHEAT: ("小麦", "こむぎ", "コムギ", "麦", "小麦粉", "wheat", "flour"),
    ALLERGEN_BUCKWHEAT: ("そば", "ソバ", "蕎麦", "buckwheat", "soba"),
    ALLERGEN_PEANUT: (
        "落花生", "らっかせい", "ピーナッツ", "ピーナツ", "南京豆",
        "peanut", "peanuts", "groundnut",
    ),
    ALLERGEN_SHRIMP: ("えび", "エビ", "海老", "shrimp", "prawn"),
    ALLERGEN_CRAB: ("かに", "カニ", "蟹", "crab"),
    ALLERGEN_WALNUT: ("くるみ", "クルミ", "胡桃", "walnut", "walnuts"),
}

_ALLERGEN_LOOKUP: Dict[str, str] = _build_alias_map(_ALLERGEN_ALIASES)

# 正規形の集合（公開; 照合層のバリデーション用）。
ALLERGEN_CANONICALS: Tuple[str, ...] = tuple(_ALLERGEN_ALIASES.keys())


# --- 配慮カテゴリ・キーワード辞書 ------------------------------------------------

# {正規形カテゴリ: (キーワード/別名タプル)}。おたより本文にも現れうる表現を含める。
_CARE_CATEGORY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    CARE_ANIMAL_CONTACT: (
        "動物接触", "動物ふれあい", "動物とのふれあい", "ふれあい動物", "動物ふれあい体験",
        "ふれあい体験", "動物", "犬", "猫", "うさぎ", "ウサギ", "ポニー", "乗馬",
        "牧場", "動物園", "小動物", "触れ合い",
        "animal contact", "petting", "petting zoo",
    ),
    CARE_LOUD_NOISE: (
        "大音量", "大きな音", "大きい音", "騒音", "爆音", "花火", "ピストル", "号砲",
        "運動会", "発表会", "音楽会", "鼓笛", "太鼓", "ブラスバンド", "スピーカー",
        "loud noise", "loud", "fireworks",
    ),
    CARE_MOTION_SICKNESS: (
        "乗物酔い", "乗り物酔い", "のりもの酔い", "車酔い", "バス酔い", "船酔い",
        "酔い止め", "長時間のバス", "長距離バス", "大型バス", "遠足バス",
        "motion sickness", "carsick", "carsickness", "travel sickness",
    ),
}

_CARE_KEYWORD_LOOKUP: Dict[str, str] = _build_alias_map(_CARE_CATEGORY_KEYWORDS)

# 正規形カテゴリの集合（公開）。
CARE_CATEGORY_CANONICALS: Tuple[str, ...] = tuple(_CARE_CATEGORY_KEYWORDS.keys())


# --- 公開 API -------------------------------------------------------------------


def normalize_allergen(term: Optional[str]) -> Optional[str]:
    """1語のアレルゲン表記を正規形へ解決する。未知語・空文字は ``None``。

    >>> normalize_allergen("たまご")
    'egg'
    >>> normalize_allergen("エッグ")
    'egg'
    >>> normalize_allergen("未知の食材") is None
    True
    """
    if term is None:
        return None
    return _ALLERGEN_LOOKUP.get(_canonical_key(term))


def normalize_allergens(terms) -> List[str]:
    """アレルゲン表記のリストを正規形リストへ。未知語は除外し、順序を保って重複排除する。"""
    result: List[str] = []
    seen = set()
    for term in terms or []:
        canonical = normalize_allergen(term)
        if canonical is not None and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def normalize_care_category(term: Optional[str]) -> Optional[str]:
    """1語の配慮カテゴリ/キーワードを正規形カテゴリへ解決する。未知語・空文字は ``None``。

    >>> normalize_care_category("犬")
    'animal_contact'
    >>> normalize_care_category("バス酔い")
    'motion_sickness'
    >>> normalize_care_category("水泳") is None
    True
    """
    if term is None:
        return None
    return _CARE_KEYWORD_LOOKUP.get(_canonical_key(term))


def normalize_care_categories(terms) -> List[str]:
    """配慮カテゴリ/キーワードのリストを正規形カテゴリへ。未知語は除外し順序保持で重複排除。"""
    result: List[str] = []
    seen = set()
    for term in terms or []:
        canonical = normalize_care_category(term)
        if canonical is not None and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def scan_care_categories(text: Optional[str]) -> List[str]:
    """自由文（おたより本文等）を走査し、含まれるキーワードから配慮カテゴリ正規形を検出する。

    照合エンジン(SOT-2733)がおたより本文から「この子に関係しうるカテゴリ」を拾うための決定論ヘルパ。
    カテゴリ定義順で返し、重複は排除する。1つも一致しなければ空リスト（未知テキストを誤検出しない）。

    >>> scan_care_categories("9/18 犬を含む動物ふれあい体験があります")
    ['animal_contact']
    """
    if not text:
        return []
    haystack = _canonical_key(text)
    found: List[str] = []
    seen = set()
    # カテゴリ定義順・キーワード長い順で走査（長い語を優先し安定した順序にする）。
    for canonical, keywords in _CARE_CATEGORY_KEYWORDS.items():
        if canonical in seen:
            continue
        for surface in keywords:
            key = _canonical_key(surface)
            if key and key in haystack:
                seen.add(canonical)
                found.append(canonical)
                break
    return found
