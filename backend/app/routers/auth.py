import os
import hmac
import hashlib
import logging
import time
import httpx
from fastapi import APIRouter, Depends, HTTPException, Cookie, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..identity import owner_id_for_email, DEFAULT_OWNER_ID  # noqa: F401 (re-exported)

router = APIRouter()

logger = logging.getLogger(__name__)

_APP_NAME = "toddler-private-rag"

# Identity Toolkit REST endpoint for server-side email/password verification.
_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
)

# Identity Toolkit REST endpoint to look up (and thereby validate) an ID token
# minted by our Firebase project — used for Google sign-in (SOT-1487).
_LOOKUP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:lookup"


def _get_firebase_api_key() -> str | None:
    return os.getenv("FIREBASE_WEB_API_KEY") or os.getenv("FIREBASE_API_KEY")


# SOT-1528(M4): セッショントークンの有効期限（秒）。既定 7 日。`SESSION_MAX_AGE_SECONDS` で上書き可能。
_DEFAULT_SESSION_MAX_AGE = 7 * 24 * 60 * 60


def _session_max_age_seconds() -> int:
    """セッションの有効期限（秒）を返す。無効値/未設定は既定値にフォールバック。"""
    raw = os.getenv("SESSION_MAX_AGE_SECONDS")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return _DEFAULT_SESSION_MAX_AGE


# SOT-1600(再オープン#2): 未ログイン(匿名)ユーザーがサンプルデータを閲覧できる
# ゲスト(デモ)ログイン。パスワード不要でデモアカウントのセッションを発行するため、
# 認証を伴わない露出になる。既定は無効(本番安全)で、`DEMO_LOGIN_ENABLED` を明示的に
# 有効化したときだけボタン/エンドポイントが機能する。
_DEFAULT_DEMO_EMAIL = "demo.user@example.com"


def _demo_login_enabled() -> bool:
    """ゲスト(デモ)ログインが有効かを返す。既定は無効(本番安全)。"""
    return os.getenv("DEMO_LOGIN_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _demo_email() -> str:
    """ゲスト(デモ)ログインで発行するデモアカウントのメール。

    既定 ``demo.user@example.com``。``SEED_REFRESH_EMAILS`` と一致させる想定で、この
    アカウントは既定オーナーの最新サンプルデータへ毎ログイン再配布(refresh)される。
    """
    return (os.getenv("DEMO_LOGIN_EMAIL", _DEFAULT_DEMO_EMAIL).strip() or _DEFAULT_DEMO_EMAIL)


class SessionRequest(BaseModel):
    email: str
    password: str


class GoogleSessionRequest(BaseModel):
    id_token: str


def _sign(owner_id: str, secret: str, issued_at: int) -> str:
    """owner_id + 発行時刻を AUTH_SECRET で HMAC 署名する（SOT-1431 / SOT-1528）。cookie 改竄防止。

    署名対象に発行時刻(issued_at)を含めることで、時刻を改竄すると署名が壊れる＝有効期限を
    サーバ側で強制できる。
    """
    message = f"{_APP_NAME}-auth:{owner_id}:{issued_at}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _build_session_token(owner_id: str, secret: str, issued_at: int | None = None) -> str:
    """署名付きセッショントークン `<owner_id>.<issued_at>.<sig>` を組み立てる（SOT-1431 / SOT-1528）。"""
    if issued_at is None:
        issued_at = int(time.time())
    return f"{owner_id}.{issued_at}.{_sign(owner_id, secret, issued_at)}"


def get_current_user(auth_token: str = Cookie(None)) -> str:
    """署名付きセッションから owner_id を復元して返す（SOT-1431 / SOT-1528）。

    cookie は `<owner_id>.<issued_at>.<hmac署名>`。署名を検証し、有効期限内であれば owner_id を返す。
    これによりログイン中のユーザーをサーバ側で一意に識別し、データを owner で分離する。

    SOT-1528(M4): 発行時刻を含まない旧形式トークン（`<owner_id>.<sig>`）は失効させ、再ログインを
    促す。これによりトークン漏えい時にも有効期限(既定7日)で自動失効する。
    """
    auth_secret = os.getenv("AUTH_SECRET")
    if not auth_secret or not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    parts = auth_token.split(".")
    if len(parts) != 3 or not all(parts):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    owner_id, issued_at_raw, signature = parts
    try:
        issued_at = int(issued_at_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    expected = _sign(owner_id, auth_secret, issued_at)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    if int(time.time()) - issued_at > _session_max_age_seconds():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )
    return owner_id


def _verify_with_firebase(email: str, password: str, api_key: str) -> str:
    """Verify email/password via Identity Toolkit REST. Returns the verified email.

    The password is never logged. Raises HTTPException on failure.
    """
    try:
        resp = httpx.post(
            _SIGN_IN_URL,
            params={"key": api_key},
            json={
                "email": email,
                "password": password,
                "returnSecureToken": True,
            },
            timeout=10.0,
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="認証サービスに接続できません",
        )

    if resp.status_code == 200:
        return resp.json().get("email", email)

    # Map Firebase REST error codes without leaking credentials.
    error_message = ""
    try:
        error_message = resp.json().get("error", {}).get("message", "")
    except Exception:
        error_message = ""

    if "TOO_MANY_ATTEMPTS" in error_message:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="ログイン試行が多すぎます。しばらく待ってから再試行してください",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="メールアドレスまたはパスワードが正しくありません",
    )


def _verify_google_id_token(id_token: str, api_key: str) -> str:
    """Firebase(Google) が発行した ID トークンを検証し、検証済みメールを返す（SOT-1487）。

    Identity Toolkit の accounts:lookup に ID トークンを渡すと、当該 Firebase
    プロジェクトが発行した有効なトークンのときだけユーザー情報が返る。他プロジェクトの
    トークンや失効/改竄トークンはエラーになるため、これでトークンの正当性を検証できる。
    トークン本文はログに出さない。失敗時は HTTPException を送出する。
    """
    try:
        resp = httpx.post(
            _LOOKUP_URL,
            params={"key": api_key},
            json={"idToken": id_token},
            timeout=10.0,
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="認証サービスに接続できません",
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Googleログインの検証に失敗しました",
        )

    users = resp.json().get("users") or []
    if not users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Googleログインの検証に失敗しました",
        )

    user = users[0]
    email = user.get("email")
    if not email or user.get("emailVerified") is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="メールアドレスが確認されていません",
        )
    return email


def _issue_session_response(
    email: str,
    auth_secret: str,
    allowed_emails: list[str],
    enforce_allowlist: bool = True,
):
    """allowlist を確認し、検証済みメールから署名付きセッション cookie を発行する。

    email/password と Google 認証で共通のセッション発行ロジック（SOT-1431 / SOT-1487）。
    ``enforce_allowlist=False`` のときは allowlist 判定を省略する（SOT-1497: Google 認証は
    検証済みメールを持つ任意のユーザーに使用を許可するため）。
    """
    if enforce_allowlist and allowed_emails and email not in allowed_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このメールアドレスは許可されていません",
        )

    # SOT-1431: 検証済みメールから安定した owner_id を導出し、署名付きセッションに格納する。
    owner_id = owner_id_for_email(email)

    # SOT-1507: 新規ユーザーの初回ログイン時に、既定オーナーの初期データをコピー配布する（案B）。
    # ベストエフォート（seeding 失敗でログインを止めない。関数内で例外は握り潰される）。
    try:
        from ..user_seed import ensure_user_seeded

        ensure_user_seeded(owner_id)
    except Exception:  # pragma: no cover - ログインを止めない保険
        logger.exception("initial-data seeding hook failed")

    token = _build_session_token(owner_id, auth_secret)
    is_production = os.getenv("APP_ENV", "local") == "production"

    response = JSONResponse(content={"success": True, "email": email})
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=is_production,
        samesite="lax",
        max_age=_session_max_age_seconds(),  # SOT-1528(M4): サーバ側の有効期限と一致させる。
        path="/",
    )
    return response


def _require_auth_config() -> tuple[str, str, list[str]]:
    """認証に必要な設定（AUTH_SECRET / API key / allowlist）を取得・検証する。"""
    auth_secret = os.getenv("AUTH_SECRET")
    api_key = _get_firebase_api_key()
    allowed_emails_str = os.getenv("ALLOWED_USER_EMAILS", "")
    allowed_emails = [e.strip() for e in allowed_emails_str.split(",") if e.strip()]

    if not auth_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SECRET not configured",
        )
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FIREBASE_WEB_API_KEY / FIREBASE_API_KEY not configured",
        )
    return auth_secret, api_key, allowed_emails


@router.post("/session")
def create_session(request: SessionRequest):
    auth_secret, api_key, allowed_emails = _require_auth_config()
    email = _verify_with_firebase(request.email, request.password, api_key)
    return _issue_session_response(email, auth_secret, allowed_emails)


@router.post("/session/google")
def create_google_session(request: GoogleSessionRequest):
    """Google 認証（Firebase ID トークン）でセッションを発行する（SOT-1487 / SOT-1497）。

    パスキー要件は Google 認証で充足する、という方針に基づく。フロントエンドは Firebase の
    Google サインインで得た ID トークンを送り、サーバ側で検証してからセッションを発行する。

    SOT-1497: Google 認証の場合は allowlist（``ALLOWED_USER_EMAILS``）による制限を行わず、
    検証済みメールを持つ任意の Google アカウントに使用を許可する（``enforce_allowlist=False``）。
    メール/パスワード認証は従来どおり allowlist で制限される。
    """
    auth_secret, api_key, allowed_emails = _require_auth_config()
    email = _verify_google_id_token(request.id_token, api_key)
    return _issue_session_response(
        email, auth_secret, allowed_emails, enforce_allowlist=False
    )


@router.get("/demo/available")
def demo_available():
    """SOT-1600: ゲスト(デモ)ログインが有効かをフロントに伝える（ボタン表示判定）。"""
    return {"enabled": _demo_login_enabled()}


@router.post("/demo")
def create_demo_session():
    """SOT-1600(再オープン#2): 未ログインユーザー向けのゲスト(デモ)セッションを発行する。

    パスワード検証なしで既定のデモアカウント（``DEMO_LOGIN_EMAIL``、既定
    ``demo.user@example.com``）のセッション cookie を発行する。このデモアカウントは
    ``SEED_REFRESH_EMAILS`` の鏡で、``_issue_session_response`` 内の seeding フックにより
    既定オーナーの最新サンプルデータへ再配布(refresh)される。allowlist は適用しない
    （誰でも利用可）。``DEMO_LOGIN_ENABLED`` が有効なときだけ許可し、無効時は 404 を返す
    （既定は無効＝本番安全）。
    """
    if not _demo_login_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="demo login is not enabled",
        )
    auth_secret = os.getenv("AUTH_SECRET")
    if not auth_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SECRET not configured",
        )
    # デモは Firebase 認証を経由しないため API key は不要。allowlist も適用しない。
    return _issue_session_response(
        _demo_email(), auth_secret, allowed_emails=[], enforce_allowlist=False
    )


@router.post("/logout")
def logout():
    response = JSONResponse(content={"success": True})
    response.delete_cookie(key="auth_token", path="/")
    return response


@router.get("/me")
def me(current_user: str = Depends(get_current_user)):
    return {"status": "authenticated"}
