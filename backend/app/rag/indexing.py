"""登録時の eager ベクトル化フック (SOT-1294).

info の登録/更新/確定/仮登録昇格のタイミングで、その info の chunk 埋め込みを
（永続キャッシュへ）作成する best-effort ヘルパー。失敗しても呼び出し元の処理を
止めないよう、例外はすべて握りつぶして warning ログにとどめる。

BackgroundTasks から呼べるよう、リクエストスコープの repo/session には依存せず、
``get_info_repo_standalone`` で専用 repo を開き、終了時に（sqlite の場合）閉じる。
"""

import logging

logger = logging.getLogger(__name__)


def index_info_id(info_id) -> None:
    """``info_id`` の最新状態を読み出し、その chunk 埋め込みを永続化する（best-effort）。"""
    repo = None
    try:
        from ..repository import get_info_repo_standalone
        from .service import RagService

        repo = get_info_repo_standalone()
        info = repo.get(info_id)
        if info is None:
            return
        RagService().index_info(info)
    except Exception as e:  # best-effort: 登録/質問フローを止めない
        logger.warning("index_info_id(%s) failed: %s", info_id, e)
    finally:
        # sqlite standalone repo はセッションを開くので閉じる。
        # firestore repo の ``db`` は遅延クライアント生成プロパティなので触らない（誤生成回避）。
        if repo is not None and type(repo).__name__.startswith("Sqlite"):
            db = getattr(repo, "db", None)
            close = getattr(db, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # pragma: no cover - defensive
                    pass
