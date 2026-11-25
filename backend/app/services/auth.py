"""认证与授权服务。

取舍说明：
- 密码用标准库 pbkdf2_hmac（26 万轮）。不引入 bcrypt 是因为 `passlib+bcrypt`
  在 4.x 上存在版本探测告警/崩溃，而 pbkdf2 在 FIPS 环境下同样合规、零依赖。
- JWT 用 PyJWT：只用 HS256，不需要 python-jose 拉进来的 ecdsa（后者有未修复的
  安全公告，见 pip-audit）。少一个依赖就少一份供应链风险。
- access token 是短时效 JWT（默认 30 分钟），refresh token 是随机不透明串，
  数据库只存 sha256，刷新时轮换 + 旧 token 立即吊销，降低被盗用窗口。
- JWT 里带 `typ`，refresh token 不能当 access 用。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import get_settings
from app.models.user import (
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_VIEWER,
)

PBKDF2_ITERATIONS = 260_000
PBKDF2_PREFIX = "pbkdf2_sha256"
ALGORITHM = "HS256"

# 权限表：路由上挂 @require("datasource:write")，权限到角色的映射只在这里定义
PERMISSIONS: dict[str, set[str]] = {
    ROLE_ADMIN: {
        "datasource:read",
        "datasource:write",
        "conversation:read",
        "conversation:write",
        "sql:write",
        "report:read",
        "report:generate",
        "schedule:read",
        "schedule:write",
        "task:read",
        "task:write",
        "user:manage",
        "audit:read",
    },
    ROLE_ANALYST: {
        "datasource:read",
        "datasource:write",
        "conversation:read",
        "conversation:write",
        "report:read",
        "report:generate",
        "schedule:read",
        "schedule:write",
        "task:read",
        "task:write",
    },
    ROLE_VIEWER: {
        "datasource:read",
        "conversation:read",
        "conversation:write",
        "report:read",
        "report:generate",
        "schedule:read",
        "task:read",
    },
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, iterations, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if prefix != PBKDF2_PREFIX:
        return False
    computed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(computed.hex(), digest_hex)


def permissions_for(role: str) -> set[str]:
    return set(PERMISSIONS.get(role, set()))


def role_has(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())


def is_valid_role(role: str) -> bool:
    return role in ALL_ROLES


# ---------------------------------------------------------------- JWT


def create_access_token(user_id: str, role: str, *, username: str = "") -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "username": username,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.auth_secret_key, algorithm=ALGORITHM)
    return token, int((expires - now).total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """解出 payload；任何问题都抛 ValueError，由调用方转成 401。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError as error:
        raise ValueError(f"invalid token: {error}") from error
    if payload.get("typ") != "access":
        raise ValueError("wrong token type")
    if not payload.get("sub"):
        raise ValueError("missing subject")
    return payload


# ---------------------------------------------------------------- refresh token


def new_refresh_token() -> tuple[str, str, datetime]:
    """返回 (明文, 哈希, 过期时间)。明文只回给客户端一次。"""
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires = datetime.utcnow() + timedelta(days=settings.refresh_token_days)
    return raw, digest, expires


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "ALL_ROLES",
    "PERMISSIONS",
    "ROLE_ADMIN",
    "ROLE_ANALYST",
    "ROLE_VIEWER",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "hash_refresh_token",
    "is_valid_role",
    "new_refresh_token",
    "permissions_for",
    "role_has",
    "verify_password",
]
