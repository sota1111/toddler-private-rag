import os
import hmac
import hashlib
import httpx
from fastapi import APIRouter, Depends, HTTPException, Cookie, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

_APP_NAME = "toddler-private-rag"

# Identity Toolkit REST endpoint for server-side email/password verification.
_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
)


class SessionRequest(BaseModel):
    email: str
    password: str


def _compute_token(secret: str) -> str:
    return hmac.new(
        secret.encode(), f"{_APP_NAME}-auth".encode(), hashlib.sha256
    ).hexdigest()


def get_current_user(auth_token: str = Cookie(None)) -> str:
    auth_secret = os.getenv("AUTH_SECRET")
    if not auth_secret or not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    expected = _compute_token(auth_secret)
    if not hmac.compare_digest(auth_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    return "authenticated"


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


@router.post("/session")
def create_session(request: SessionRequest):
    auth_secret = os.getenv("AUTH_SECRET")
    api_key = os.getenv("FIREBASE_API_KEY")
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
            detail="FIREBASE_API_KEY not configured",
        )

    email = _verify_with_firebase(request.email, request.password, api_key)

    if allowed_emails and email not in allowed_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このメールアドレスは許可されていません",
        )

    token = _compute_token(auth_secret)
    is_production = os.getenv("APP_ENV", "local") == "production"

    response = JSONResponse(content={"success": True, "email": email})
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=is_production,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    return response


@router.post("/logout")
def logout():
    response = JSONResponse(content={"success": True})
    response.delete_cookie(key="auth_token", path="/")
    return response


@router.get("/me")
def me(current_user: str = Depends(get_current_user)):
    return {"status": "authenticated"}
