import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _get_required_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Required environment variable {key!r} is not set")
    return value


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


def create_access_token(username: str) -> str:
    secret_key = _get_required_env("AUTH_SECRET_KEY")
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, secret_key, algorithm="HS256")


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    secret_key = _get_required_env("AUTH_SECRET_KEY")
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest):
    expected_username = _get_required_env("AUTH_USERNAME")
    expected_password = _get_required_env("AUTH_PASSWORD")
    if request.username != expected_username or request.password != expected_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token(request.username)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(current_user: str = Depends(get_current_user)):
    return {"username": current_user}


@router.post("/logout")
def logout():
    return {"message": "logged out"}
