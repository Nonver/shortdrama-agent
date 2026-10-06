"""密码哈希、JWT、一次性存储（验证码 / 黑名单），本地用进程内存储。"""
from __future__ import annotations
import hashlib
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from jose import jwt

from .config import settings

# ---------- 密码哈希（pbkdf2，无第三方依赖） ----------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, dk = stored.split("$")
        if algo != "pbkdf2":
            return False
        test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
        return secrets.compare_digest(test.hex(), dk)
    except Exception:
        return False


# ---------- JWT ----------
def create_access_token(user_id: int, account_type: str, membership_level: str = "free",
                        roles: list[str] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": account_type,
        "level": membership_level,
        "roles": roles or ([ "admin" ] if account_type == "admin" else [ "user" ]),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


# ---------- 进程内一次性存储（验证码 / token 黑名单），单机本地足够 ----------
class KVStore:
    def __init__(self):
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: object, ttl: int):
        with self._lock:
            self._data[key] = (time.time() + ttl, value)

    def get(self, key: str, pop: bool = False):
        with self._lock:
            if key not in self._data:
                return None
            exp, val = self._data[key]
            if time.time() > exp:
                self._data.pop(key, None)
                return None
            if pop:
                self._data.pop(key, None)
            return val

    def delete(self, key: str):
        with self._lock:
            self._data.pop(key, None)


kv = KVStore()


def new_id() -> str:
    return secrets.token_hex(16)


def now() -> datetime:
    return datetime.now(timezone.utc)
