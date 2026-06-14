import os
import hmac
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Cookie, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth as firebase_auth

if not firebase_admin._apps:
    firebase_admin.initialize_app()

router = APIRouter()

_APP_NAME = "toddler-private-rag"


class SessionRequest(BaseModel):
    idToken: str


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


@router.post("/session")
def create_session(request: SessionRequest):
    auth_secret = os.getenv("AUTH_SECRET")
    allowed_emails_str = os.getenv("ALLOWED_USER_EMAILS", "")
    allowed_emails = [e.strip() for e in allowed_emails_str.split(",") if e.strip()]

    if not auth_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SECRET not configured",
        )

    try:
        decoded = firebase_auth.verify_id_token(request.idToken)
        email: str = decoded.get("email", "")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase ID token",
        )

    if allowed_emails and email not in allowed_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not allowed",
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
