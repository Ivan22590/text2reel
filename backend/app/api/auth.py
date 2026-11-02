"""Demo login (FR-5.6): one user from .env, HMAC-signed cookie."""

import hashlib
import hmac

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "t2r_session"


class Credentials(BaseModel):
    username: str
    password: str


def _sign(username: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, username.encode(), hashlib.sha256).hexdigest()


def require_user(t2r_session: str | None = Cookie(default=None)) -> str:
    if t2r_session and ":" in t2r_session:
        username, signature = t2r_session.rsplit(":", 1)
        if hmac.compare_digest(signature, _sign(username)):
            return username
    raise HTTPException(401, "Требуется вход")


@router.post("/login")
def login(credentials: Credentials, response: Response) -> dict:
    settings = get_settings()
    ok_user = hmac.compare_digest(credentials.username, settings.demo_user)
    ok_pass = hmac.compare_digest(credentials.password, settings.demo_password)
    if not (ok_user and ok_pass):
        raise HTTPException(401, "Неверный логин или пароль")
    response.set_cookie(
        COOKIE, f"{credentials.username}:{_sign(credentials.username)}",
        httponly=True, samesite="lax", secure=settings.app_env == "prod", max_age=7 * 86400,
    )  # fmt: skip
    return {"username": credentials.username}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(t2r_session: str | None = Cookie(default=None)) -> dict:
    return {"username": require_user(t2r_session)}
