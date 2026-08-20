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


# ---------------------------------------------------------------------------
# Agent E2E Regression Cases (SOT-1568)
#
# End-to-end golden cases for the submission-preparation AGENT (the product's
# core value: turning a nursery-school letter into dated "やること" tasks). Each
# case runs the real agent pipeline
#   ``extract_submission_documents -> build_submission_task_drafts``
# with the two external LLM boundaries stubbed DETERMINISTICALLY so the gate is
# CI-stable and offline (no network / no real Gemini):
#   - ``llm_docs``   -> stubs ``submission_agent._llm_extract_documents`` (the
#                       document-extraction LLM). ``None`` = let the LLM return
#                       nothing and exercise the REAL offline dictionary inference
#                       (``_dictionary_inferred_documents``) instead.
#   - ``enrich``     -> stubs ``ai_client.generate_grounded_with_sources`` (the
#                       Google-Search grounding). Its ``steps``/``lead_time_days``
#                       drive the REAL deterministic deadline back-calc.
#
# The cases collectively measure four qualities that were previously only unit
# tested and NOT gated (items 1/2/3/5 of the DevOps eval):
#   ① Agent E2E Regression  — the whole letter->tasks path runs as one named gate.
#   ② Task generation       — coverage/precision of the generated "やること".
#   ③ Deadline back-calc     — exactness of the reverse-calculated dates.
#   ⑤ Ambiguity handling     — no date fabrication / inferred(要確認) / no over-detection.
#
# Each case:
# {
#   "id", "letter",
#   "final_due_iso": Optional[str],          # explicit anchor passed to the agent
#   "today": Optional["YYYY-MM-DD"],         # pin _today() for forward-fallback determinism
#   "llm_docs": Optional[list[{name,due_date}]],  # None -> real dictionary inference
#   "enrich": {steps, lead_time_days, needs_company_issuance, source},
#   "expected_task_docs": list[str],         # ② doc names that MUST become tasks (coverage)
#   "forbidden_task_docs": list[str],        # ② names that must NOT appear (precision)
#   "expected_due_dates": list[str],         # ③ exact due_date per draft, in order ([] = skip)
#   "expect_inferred_notice": bool,          # ⑤(b) 推定(要確認) 導線が出る
#   "expect_no_fabricated_deadline": bool,   # ⑤(a) 締切不明→最終提出期限を捏造しない
#   "expect_empty": bool,                    # ⑤(c) 一般文→書類を湧かせない(過検出ゼロ)
# }

# Grounding-step preset for the README golden example (就労証明書, 2026/7/30 → 7/9).
# Steps in execution order; back-calc from 7/30: 提出3→7/27, 確認1→7/26, 発行14→7/12,
# テンプレ入手3→7/09 (= 準備開始日, matches README 2.1 実例).
_WORK_CERT_STEPS = [
    {"name": "テンプレート入手", "lead_time_days": 3},
    {"name": "会社に証明書発行を依頼", "lead_time_days": 14},
    {"name": "記載内容を確認", "lead_time_days": 1},
    {"name": "市町村に提出", "lead_time_days": 3},
]

AGENT_EVAL_CASES = [
    # ③ 締切逆算 (README golden) + ② coverage: 7/30 提出 → 準備開始 7/9 まで逆算。
    {
        "id": "deadline_backcalc_work_certificate",
        "letter": (
            "保育を必要とする状況の確認のため、就労証明書を 2026/7/30 までに"
            "ご提出ください。\n"
        ),
        "final_due_iso": None,
        "today": None,
        "llm_docs": [{"name": "就労証明書", "due_date": "2026-07-30"}],
        "enrich": {
            "steps": _WORK_CERT_STEPS,
            "lead_time_days": None,
            "needs_company_issuance": True,
            "source": "https://example.go.jp",
        },
        "expected_task_docs": ["就労証明書"],
        "forbidden_task_docs": [],
        "expected_due_dates": ["2026-07-09", "2026-07-12", "2026-07-26", "2026-07-27"],
        "expect_inferred_notice": False,
        "expect_no_fabricated_deadline": False,
        "expect_empty": False,
    },
    # ② タスク生成 coverage + precision: 明記された2書類が両方タスク化され、余計な書類は出ない。
    {
        "id": "task_generation_multi_document",
        "letter": (
            "入園のしおり\n"
            "健康調査票を 2026-05-01 までに提出してください。\n"
            "就労証明書は 2026-05-10 までにご提出ください。\n"
            "運動会は 2026-05-20 に開催します。\n"
        ),
        "final_due_iso": None,
        "today": None,
        "llm_docs": [
            {"name": "健康調査票", "due_date": "2026-05-01"},
            {"name": "就労証明書", "due_date": "2026-05-10"},
        ],
        "enrich": {
            "steps": [{"name": "記入して提出", "lead_time_days": 3}],
            "lead_time_days": None,
            "needs_company_issuance": None,
            "source": "https://example.go.jp",
        },
        "expected_task_docs": ["健康調査票", "就労証明書"],
        "forbidden_task_docs": ["運動会", "遠足"],
        "expected_due_dates": [],
        "expect_inferred_notice": False,
        "expect_no_fabricated_deadline": False,
        "expect_empty": False,
    },
    # ⑤(a) 締切不明: 本文に日付が無い → 最終提出期限を捏造せず前向きフォールバック。
    {
        "id": "ambiguous_no_deadline_forward_fallback",
        "letter": (
            "入園のしおり\n"
            "在籍証明書を提出してください。会社/勤務先の発行が必要です。\n"
        ),
        "final_due_iso": None,
        "today": "2026-06-01",
        "llm_docs": [{"name": "在籍証明書", "due_date": ""}],
        "enrich": {
            "steps": [
                {"name": "会社に依頼", "lead_time_days": 3},
                {"name": "受け取って提出", "lead_time_days": 14},
            ],
            "lead_time_days": None,
            "needs_company_issuance": True,
            "source": "https://example.go.jp",
        },
        "expected_task_docs": ["在籍証明書"],
        "forbidden_task_docs": [],
        # 本日(2026-06-01)起点で前向き累積: +3=6/4, +14=6/18。
        "expected_due_dates": ["2026-06-04", "2026-06-18"],
        "expect_inferred_notice": False,
        "expect_no_fabricated_deadline": True,
        "expect_empty": False,
    },
    # ⑤(b) 手続き名のみ: 書類名は本文に無いが手続きキーワードから就労証明書を推定し、
    #      推定(要確認)導線を必ず出す。llm_docs=None で REAL 辞書推論を通す。
    {
        "id": "ambiguous_procedure_only_inferred",
        "letter": (
            "保育施設在籍にかかる現況確認の手続きはお済でしょうか。\n"
            "2026-07-31 までにご対応ください。\n"
        ),
        "final_due_iso": None,
        "today": None,
        "llm_docs": None,  # LLM returns nothing -> exercise real dictionary inference
        "enrich": {
            "steps": [],
            "lead_time_days": None,
            "needs_company_issuance": None,
            "source": "",
        },
        "expected_task_docs": ["就労証明書"],
        "forbidden_task_docs": [],
        "expected_due_dates": [],
        "expect_inferred_notice": True,
        "expect_no_fabricated_deadline": False,
        "expect_empty": False,
    },
    # ⑤(c) 一般文: 手続きキーワードも書類も無い → 書類を湧かせない(過検出ゼロ)。
    {
        "id": "ambiguous_general_notice_no_overdetection",
        "letter": (
            "入園のしおり\n"
            "運動会は 2026-05-20 に開催します。上履きを持たせてください。\n"
        ),
        "final_due_iso": None,
        "today": None,
        "llm_docs": [],  # LLM finds no submission document
        "enrich": {
            "steps": [],
            "lead_time_days": None,
            "needs_company_issuance": None,
            "source": "",
        },
        "expected_task_docs": [],
        "forbidden_task_docs": ["就労証明書", "在籍証明書", "運動会"],
        "expected_due_dates": [],
        "expect_inferred_notice": False,
        "expect_no_fabricated_deadline": False,
        "expect_empty": True,
    },
]


# ---------------------------------------------------------------------------
# SOT-2735: 個別配慮照合（care-matching）eval-gate 用 golden dataset
# ---------------------------------------------------------------------------
#
# SOT-2733 の照合エンジン ``app.care_matching.match_notice`` を、プロダクト価値の観点
# （「この子に関係する要確認をちゃんと拾う / 無関係でうるさくしない / 断定しない」）で
# 回帰計測するための golden。Expected Experience 型の5類型を網羅する:
#
#   1. menu_allergen     献立 ``menu_json`` の原材料 × プロファイルのアレルゲン
#   2. event_care        おたより本文の行事 × プロファイルの配慮カテゴリ
#   3. irrelevant        無関係な文書 → 要確認を湧かせない（無関係抑制）
#   4. info_insufficient 情報不足文書 → 断定せず棄権（abstain）を明示する
#   5. conflict          相反情報（「使用しません」「対応済み」等）でも安全側で要確認を残す
#
# 各ケースの宣言フィールド:
#   - profile            : ``match_notice`` に渡す個別配慮プロファイル（dict でも動く）
#   - notice_text        : おたより本文（None 可）
#   - menu_json          : 献立 JSON（None 可）
#   - expected_attention : 検出されるべき (kind, canonical) の集合（発見率 Recall の分子）
#   - expected_suppressed: 出てはいけない (kind, canonical)（無関係抑制の分子）
#   - expect_abstain     : status=abstain（情報不足のため要確認）が必要か（安全棄権）
#
# kind は care_matching の安定キー "allergen" / "care_category"。
# 決定論のみで評価する（``use_llm=False``）ため CI でネットワーク不要・安定。


def _cm_menu(date, *, morning_snack=None, lunch=None, afternoon_snack=None,
             red=None, yellow=None, green=None, other=None):
    """care-matching golden 用の 1日献立 ``menu_json`` を組み立てる小ヘルパ。"""
    return {
        "month": date[:7],
        "days": [
            {
                "date": date,
                "morning_snack": morning_snack or [],
                "lunch": lunch or [],
                "afternoon_snack": afternoon_snack or [],
                "main_ingredients": {
                    "red": red or [],
                    "yellow": yellow or [],
                    "green": green or [],
                    "other": other or [],
                },
            }
        ],
    }


CARE_MATCHING_EVAL_CASES = [
    # === 1. 献立 × アレルゲン（陽性検出 + 無関係抑制） ===========================
    {
        "id": "menu_allergen_egg_with_buckwheat_distractor",
        "archetype": "menu_allergen",
        "profile": {"allergens": ["たまご", "そば"], "care_categories": [], "free_text": ""},
        "notice_text": "9月の献立表をお配りします。ご確認ください。",
        "menu_json": _cm_menu("2026-09-01", lunch=["親子丼"], red=["鶏卵", "鶏肉"]),
        # 献立に鶏卵→egg を第一根拠(high)で拾う。そばは献立に無い→抑制。
        "expected_attention": [("allergen", "egg")],
        "expected_suppressed": [("allergen", "buckwheat")],
        "expect_abstain": False,
    },
    {
        "id": "menu_allergen_milk_and_wheat",
        "archetype": "menu_allergen",
        "profile": {"allergens": ["牛乳", "小麦"], "care_categories": [], "free_text": ""},
        "notice_text": "今月の給食献立のご案内です。",
        "menu_json": _cm_menu("2026-09-02", lunch=["クリームシチュー"], red=["牛乳"], yellow=["小麦粉"]),
        "expected_attention": [("allergen", "milk"), ("allergen", "wheat")],
        "expected_suppressed": [],
        "expect_abstain": False,
    },
    {
        "id": "menu_allergen_egg_composite_substring",
        "archetype": "menu_allergen",
        "profile": {"allergens": ["卵"], "care_categories": [], "free_text": ""},
        "notice_text": None,
        # 辞書完全一致しない「厚焼き玉子」でも部分一致で egg を拾える（安全側）。
        "menu_json": _cm_menu("2026-09-03", lunch=["厚焼き玉子", "みそ汁"]),
        "expected_attention": [("allergen", "egg")],
        "expected_suppressed": [],
        "expect_abstain": False,
    },

    # === 2. 行事 × 配慮カテゴリ（陽性検出 + 無関係抑制） =========================
    {
        "id": "event_care_animal_contact_with_noise_distractor",
        "archetype": "event_care",
        "profile": {"allergens": [], "care_categories": ["動物接触", "大音量"], "free_text": ""},
        "notice_text": "9/18に犬とのふれあい体験を予定しています。楽しみにしていてください。",
        "menu_json": None,
        "expected_attention": [("care_category", "animal_contact")],
        "expected_suppressed": [("care_category", "loud_noise")],
        "expect_abstain": False,
    },
    {
        "id": "event_care_loud_noise",
        "archetype": "event_care",
        "profile": {"allergens": [], "care_categories": ["大音量"], "free_text": ""},
        "notice_text": "運動会の予行練習でピストルの号砲を鳴らします。",
        "menu_json": None,
        "expected_attention": [("care_category", "loud_noise")],
        "expected_suppressed": [],
        "expect_abstain": False,
    },
    {
        "id": "event_care_motion_sickness",
        "archetype": "event_care",
        "profile": {"allergens": [], "care_categories": ["乗り物酔い"], "free_text": ""},
        "notice_text": "秋の遠足は大型バスで移動します。酔いやすいお子様はご相談ください。",
        "menu_json": None,
        "expected_attention": [("care_category", "motion_sickness")],
        "expected_suppressed": [],
        "expect_abstain": False,
    },

    # === 3. 無関係文書（要確認を湧かせない = 無関係抑制） =======================
    {
        "id": "irrelevant_general_with_nonmatching_menu",
        "archetype": "irrelevant",
        "profile": {"allergens": ["卵", "牛乳"], "care_categories": ["動物接触"], "free_text": ""},
        "notice_text": "今日は良い天気で、園庭で元気に遊びました。またのご参加をお待ちしています。",
        # 献立はあるが該当食材なし → has_menu=True で棄権も湧かない。
        "menu_json": _cm_menu("2026-09-04", lunch=["カレーライス"], green=["にんじん", "たまねぎ"]),
        "expected_attention": [],
        "expected_suppressed": [
            ("allergen", "egg"), ("allergen", "milk"), ("care_category", "animal_contact"),
        ],
        "expect_abstain": False,
    },
    {
        "id": "irrelevant_admin_notice_no_food_event",
        "archetype": "irrelevant",
        "profile": {"allergens": ["えび"], "care_categories": [], "free_text": ""},
        # 食に関する予定キーワードが無い → 情報不足でもなく、棄権も湧かない純粋な無関係。
        "notice_text": "保護者会を開催します。ご都合のつく範囲でご出席ください。",
        "menu_json": None,
        "expected_attention": [],
        "expected_suppressed": [("allergen", "shrimp")],
        "expect_abstain": False,
    },

    # === 4. 情報不足文書（断定せず棄権 = 安全棄権） =============================
    {
        "id": "info_insufficient_food_event_without_menu",
        "archetype": "info_insufficient",
        "profile": {"allergens": ["卵", "落花生"], "care_categories": [], "free_text": ""},
        # 食に関する予定はあるが献立の原材料情報が無い → 断定できず棄権（要確認）。
        "notice_text": "来週のクッキング保育を行います。持ち物は追ってお知らせします。",
        "menu_json": None,
        "expected_attention": [],
        "expected_suppressed": [],
        "expect_abstain": True,
    },

    # === 5. 相反情報（安全側で要確認を残す・断定しない） ========================
    {
        "id": "conflict_allergen_in_menu_but_notice_claims_handled",
        "archetype": "conflict",
        "profile": {"allergens": ["卵"], "care_categories": [], "free_text": ""},
        # 本文は「対応済み」と言うが、献立に鶏卵がある → 断定せず要確認を残す。
        "notice_text": "アレルギー対応として除去食をご用意しますのでご安心ください。",
        "menu_json": _cm_menu("2026-09-05", lunch=["オムレツ"], red=["鶏卵"]),
        "expected_attention": [("allergen", "egg")],
        "expected_suppressed": [],
        "expect_abstain": False,
    },
    {
        "id": "conflict_negation_peanut_still_flagged",
        "archetype": "conflict",
        "profile": {"allergens": ["落花生"], "care_categories": [], "free_text": ""},
        # 本文は「使用していません」だが、言及がある以上は安全側で要確認（過検出許容）。
        "notice_text": "本日のおやつにピーナッツは使用していません。ご安心ください。",
        # 献立を添えて has_menu=True にし、食イベント棄権(棄権1)は湧かせない（相反=断定しないの純検証）。
        "menu_json": _cm_menu("2026-09-06", afternoon_snack=["クッキー"]),
        "expected_attention": [("allergen", "peanut")],
        "expected_suppressed": [],
        "expect_abstain": False,
    },
]
