"""SOT-2730: アレルゲン別名辞書・配慮カテゴリ正規化（決定論）の単体テスト。

検証観点（受け入れ条件対応）:
- 主要アレルゲンの表記ゆれが正規形へ集約される。
- MVP対象3配慮カテゴリのキーワードが正規化される。
- 決定論的（同入力→同出力）。
- 未知語を誤って正規化しない（None / 空）。
"""

import pytest

from app import care_normalization as cn


# --- アレルゲン別名正規化 -------------------------------------------------------


@pytest.mark.parametrize(
    "surface,expected",
    [
        # 卵の表記ゆれ（issue 例）
        ("卵", "egg"),
        ("たまご", "egg"),
        ("タマゴ", "egg"),
        ("玉子", "egg"),
        ("鶏卵", "egg"),
        ("エッグ", "egg"),
        ("egg", "egg"),
        ("Egg", "egg"),
        ("EGG", "egg"),
        ("  egg  ", "egg"),  # 前後空白
        ("ｴｯｸﾞ", "egg"),  # 半角カナ（NFKC）
        # 乳
        ("牛乳", "milk"),
        ("ミルク", "milk"),
        ("乳製品", "milk"),
        ("milk", "milk"),
        # 小麦
        ("小麦", "wheat"),
        ("こむぎ", "wheat"),
        ("小麦粉", "wheat"),
        # そば
        ("そば", "buckwheat"),
        ("蕎麦", "buckwheat"),
        # 落花生
        ("落花生", "peanut"),
        ("ピーナッツ", "peanut"),
        ("ピーナツ", "peanut"),
        # えび・かに・くるみ
        ("えび", "shrimp"),
        ("海老", "shrimp"),
        ("かに", "crab"),
        ("蟹", "crab"),
        ("くるみ", "walnut"),
        ("胡桃", "walnut"),
    ],
)
def test_normalize_allergen_maps_variants_to_canonical(surface, expected):
    assert cn.normalize_allergen(surface) == expected


@pytest.mark.parametrize("unknown", ["未知の食材", "りんご", "apple", "", "   ", "水", "醤油"])
def test_normalize_allergen_unknown_is_none(unknown):
    # 未知語は誤って正規化しない。
    assert cn.normalize_allergen(unknown) is None


def test_normalize_allergen_none_input_is_none():
    assert cn.normalize_allergen(None) is None


def test_normalize_allergens_list_dedup_and_order_and_drops_unknown():
    result = cn.normalize_allergens(["たまご", "玉子", "牛乳", "未知", "小麦", "egg"])
    # 「たまご」「玉子」「egg」は egg に集約 → 1つ、順序は初出順、未知は除外。
    assert result == ["egg", "milk", "wheat"]


def test_normalize_allergens_handles_none_and_empty():
    assert cn.normalize_allergens(None) == []
    assert cn.normalize_allergens([]) == []
    assert cn.normalize_allergens(["", None, "  "]) == []


# --- 配慮カテゴリ正規化 ---------------------------------------------------------


@pytest.mark.parametrize(
    "surface,expected",
    [
        # 動物接触
        ("動物接触", cn.CARE_ANIMAL_CONTACT),
        ("動物ふれあい", cn.CARE_ANIMAL_CONTACT),
        ("犬", cn.CARE_ANIMAL_CONTACT),
        ("ウサギ", cn.CARE_ANIMAL_CONTACT),
        ("動物園", cn.CARE_ANIMAL_CONTACT),
        ("petting zoo", cn.CARE_ANIMAL_CONTACT),
        # 大音量
        ("大音量", cn.CARE_LOUD_NOISE),
        ("大きな音", cn.CARE_LOUD_NOISE),
        ("運動会", cn.CARE_LOUD_NOISE),
        ("花火", cn.CARE_LOUD_NOISE),
        ("loud noise", cn.CARE_LOUD_NOISE),
        # 乗物酔い
        ("乗物酔い", cn.CARE_MOTION_SICKNESS),
        ("乗り物酔い", cn.CARE_MOTION_SICKNESS),
        ("バス酔い", cn.CARE_MOTION_SICKNESS),
        ("車酔い", cn.CARE_MOTION_SICKNESS),
        ("motion sickness", cn.CARE_MOTION_SICKNESS),
    ],
)
def test_normalize_care_category_maps_keywords(surface, expected):
    assert cn.normalize_care_category(surface) == expected


@pytest.mark.parametrize("unknown", ["水泳", "読書", "算数", "", "   ", "unrelated"])
def test_normalize_care_category_unknown_is_none(unknown):
    assert cn.normalize_care_category(unknown) is None


def test_normalize_care_category_none_input_is_none():
    assert cn.normalize_care_category(None) is None


def test_normalize_care_categories_covers_three_mvp_categories():
    result = cn.normalize_care_categories(
        ["犬", "運動会", "バス酔い", "動物ふれあい", "未知"]
    )
    # 3カテゴリすべてが正規化され、動物系は1つに集約、未知は除外。
    assert result == [
        cn.CARE_ANIMAL_CONTACT,
        cn.CARE_LOUD_NOISE,
        cn.CARE_MOTION_SICKNESS,
    ]


# --- テキスト走査 ---------------------------------------------------------------


def test_scan_care_categories_from_notice_text():
    text = "9/18 犬を含む動物ふれあい体験があります。9/25 運動会。"
    assert cn.scan_care_categories(text) == [
        cn.CARE_ANIMAL_CONTACT,
        cn.CARE_LOUD_NOISE,
    ]


def test_scan_care_categories_no_match_is_empty():
    assert cn.scan_care_categories("図書の貸出について") == []
    assert cn.scan_care_categories("") == []
    assert cn.scan_care_categories(None) == []


# --- 決定論 / 不変条件 -----------------------------------------------------------


def test_normalization_is_deterministic():
    for _ in range(3):
        assert cn.normalize_allergen("エッグ") == "egg"
        assert cn.normalize_care_category("大きな音") == cn.CARE_LOUD_NOISE
        assert cn.scan_care_categories("バス遠足で車酔いが心配") == [cn.CARE_MOTION_SICKNESS]


def test_canonical_sets_exposed():
    assert cn.ALLERGEN_EGG in cn.ALLERGEN_CANONICALS
    assert set(cn.CARE_CATEGORY_CANONICALS) == {
        cn.CARE_ANIMAL_CONTACT,
        cn.CARE_LOUD_NOISE,
        cn.CARE_MOTION_SICKNESS,
    }
    # 特定原材料8品目がすべて正規形として存在する。
    assert set(cn.ALLERGEN_CANONICALS) == {
        "egg", "milk", "wheat", "buckwheat", "peanut", "shrimp", "crab", "walnut",
    }
