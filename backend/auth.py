"""Вход и проверка ролей.

Токен подписывается HMAC и ничего не хранит в памяти сервера — поэтому
работает при нескольких копиях бэкенда (docker compose --scale backend=N).
"""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import db

SECRET = os.getenv("AUTH_SECRET", "motiv-hackathon-secret").encode()
TOKEN_TTL = 12 * 3600   # смена дежурного

ROLE_NAMES = {"admin": "Администратор", "duty": "Дежурный", "engineer": "Инженер"}

router = APIRouter(prefix="/api", tags=["auth"])


def _sign(payload: bytes) -> str:
    return hmac.new(SECRET, payload, hashlib.sha256).hexdigest()


def make_token(user: dict) -> str:
    payload = json.dumps({"u": user["USERNAME"], "r": user["ROLE"], "n": user["FULL_NAME"],
                          "exp": int(time.time()) + TOKEN_TTL}).encode()
    return base64.urlsafe_b64encode(payload).decode() + "." + _sign(payload)


def read_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(body.encode())
        if not hmac.compare_digest(sig, _sign(payload)):
            raise ValueError
        data = json.loads(payload)
    except Exception:
        raise HTTPException(401, "Нужно войти заново")
    if data["exp"] < time.time():
        raise HTTPException(401, "Сессия истекла, войдите заново")
    return {"username": data["u"], "role": data["r"], "full_name": data["n"]}


def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Нужно войти")
    return read_token(authorization[7:])


def require_role(*roles: str):
    """Зависимость FastAPI: пропускает только перечисленные роли, остальным — 403."""
    def check(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Недостаточно прав для этого действия")
        return user
    return check


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    user = await db.fetch_one(
        "SELECT USERNAME, ROLE, FULL_NAME FROM USERS WHERE USERNAME = %s AND PASSWORD_HASH = SHA2(%s, 256)",
        (body.username.strip(), body.password),
    )
    if not user:
        raise HTTPException(401, "Неверный логин или пароль")
    return {"token": make_token(user), "username": user["USERNAME"], "role": user["ROLE"],
            "role_name": ROLE_NAMES[user["ROLE"]], "full_name": user["FULL_NAME"]}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return {**user, "role_name": ROLE_NAMES[user["role"]]}
