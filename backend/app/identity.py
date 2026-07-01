"""SOT-1431: ユーザー識別（マルチテナント分離）の共通ヘルパー。

検証済みメールから安定した owner_id を導出する（案A）。auth.py（セッション発行/検証）と
repository.py（owner 絞り込み）の双方から参照するため、循環 import を避けて独立モジュールに置く。
"""

import hashlib


def owner_id_for_email(email: str) -> str:
    """検証済みメールから安定した owner_id を導出する。

    小文字化・前後空白除去した email の sha256 先頭32桁。メール文字列そのものを保存/送出せず、
    決定的なIDだけを扱う（cookie に載るのはこの owner_id と署名のみ）。
    """
    normalized = (email or "").strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


# 既存(owner 未設定)データの帰属先＝現行の主ユーザー（SOT-1431 の人間選択 (a)）。
# 保存行の owner_id が NULL/未設定なら、この既定 owner のデータとして扱う。
DEFAULT_OWNER_ID = owner_id_for_email("sota.moro@gmail.com")
