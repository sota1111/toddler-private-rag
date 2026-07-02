"""
Evaluation dataset for OCR and RAG performance.
Includes realistic Japanese nursery school (保育園) letter style text.
"""

# OCR Evaluation Cases
# Each case: { "id", "raw_text", "expected_dates", "expected_items" }
OCR_EVAL_CASES = [
    {
        "id": "standard_letter",
        "raw_text": """
令和5年10月25日
保護者各位
秋の遠足のお知らせ
11月10日は遠足です。
持ち物:
・お弁当
・水筒
・レジャーシート
・着替え
よろしくお願いします。
""",
        "expected_dates": ["令和5年10月25日", "11月10日"],
        "expected_items": ["・お弁当", "・水筒", "・レジャーシート", "・着替え"]
    },
    {
        "id": "various_dates",
        "raw_text": """
2023/12/01
クリスマス会の案内
開催日: 2023-12-24
予備日: 12月25日
持ち物はありません。
""",
        "expected_dates": ["2023/12/01", "2023-12-24", "12月25日"],
        "expected_items": []
    },
    {
        "id": "bullet_points",
        "raw_text": """
準備するもの
* ハンカチ
- ティッシュ
● コップ
○ 歯ブラシ
〇 タオル
""",
        "expected_dates": [],
        "expected_items": ["* ハンカチ", "- ティッシュ", "● コップ", "○ 歯ブラシ", "〇 タオル"]
    },
    {
        "id": "heading_items",
        "raw_text": """
1月15日 もちつき大会
用意するもの
上履き
エプロン
三角巾
汚れてもいい服
""",
        "expected_dates": ["1月15日"],
        "expected_items": ["上履き", "エプロン", "三角巾", "汚れてもいい服"]
    },
    {
        "id": "mixed_text",
        "raw_text": """
令和6年1月1日
あけましておめでとうございます。
・1月4日から保育開始です。
・1月10日：避難訓練
持ち物
特になし
""",
        "expected_dates": ["令和6年1月1日", "1月4日", "1月10日"],
        "expected_items": ["・1月4日から保育開始です。", "・1月10日：避難訓練", "特になし"]
    },
    {
        "id": "empty",
        "raw_text": "   \n  \t ",
        "expected_dates": [],
        "expected_items": []
    }
]

# RAG Evaluation Cases
# Shared Corpus
# NOTE: We use spaces to help FakeEmbeddingProvider tokenize Japanese text.
RAG_CORPUS = [
    {
        "id": 1,
        "title": "遠足 の お知らせ",
        "content": "秋 の 遠足 は 11月10日 に 上野動物園 に 行きます。 持ち物 は お弁当 、 水筒 、 レジャーシート です。 雨天 の 場合 は 11月17日 に 延期 します。",
        "attachments": [
            {
                "original_filename": "ensoku.pdf",
                "ocr_text": "遠足 の しおり ： 集合 時間 は 9時 です。 おやつ は 300円 まで。"
            }
        ]
    },
    {
        "id": 2,
        "title": "給食 だより",
        "content": "11月 の 献立 を お知らせ します。 今月 の 目標 は 「 何でも 食べよう 」 です。 アレルギー 対応 が 必要 な 方 は 申し出てください。",
        "attachments": []
    },
    {
        "id": 3,
        "title": "感染症 対策 について",
        "content": "インフルエンザ が 流行 しています。 手洗い 、 うがい を 徹底 してください。 発熱 が ある 場合 は 登園 を 控えて ください。",
        "attachments": []
    }
]

# Each case: { "id", "query", "top_k", "expected_top_info_id", "expected_keywords" }
RAG_EVAL_CASES = [
    {
        "id": "ensoku_query",
        "query": "遠足 持ち物 何",
        "top_k": 3,
        "expected_top_info_id": 1,
        "expected_keywords": ["お弁当", "水筒", "レジャーシート"]
    },
    {
        "id": "ensoku_date_query",
        "query": "遠足 いつ",
        "top_k": 3,
        "expected_top_info_id": 1,
        "expected_keywords": ["11月10日"]
    },
    {
        "id": "ensoku_ocr_query",
        "query": "遠足 集合 時間",
        "top_k": 3,
        "expected_top_info_id": 1,
        "expected_keywords": ["9時"]
    },
    {
        "id": "allergy_query",
        "query": "アレルギー 相談",
        "top_k": 3,
        "expected_top_info_id": 2,
        "expected_keywords": ["アレルギー"]
    },
    {
        "id": "illness_query",
        "query": "熱 登園",
        "top_k": 3,
        "expected_top_info_id": 3,
        "expected_keywords": ["登園", "控えて"]
    }
]

# Refusal Evaluation Cases (SOT-1471)
# The agent must NOT fabricate an answer when nothing relevant is retrieved.
# Evaluated against an EMPTY index: the answer must be a refusal (no sources,
# a "見つかりませんでした" style message) rather than a hallucinated response.
# Each case: { "id", "query" }
REFUSAL_EVAL_CASES = [
    {"id": "unrelated_stock", "query": "株価 の 予想 を 教えて"},
    {"id": "out_of_scope_weather", "query": "明日 の 天気 は"},
]
