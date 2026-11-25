"""认证 API：登录 / 刷新 / 登出 / 当前用户 / 用户管理。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_permissions, get_current_user, require
from app.config import get_settings
from app.core.errors import AppError
from app.database import get_db
from app.models.user import RefreshToken, User
from app.services.audit import record_audit
from app.services.auth import (
    ALL_ROLES,
    create_access_token,
    hash_password,
    hash_refresh_token,
    is_valid_role,
    new_refresh_token,
    role_has,
    verify_password,
)
from app.services.rate_limit import limiters

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ------------------------------------------------------------------ schemas


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: str = "viewer"
    display_name: str = ""


class UserUpdateRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = None


# ------------------------------------------------------------------ helpers


async def _issue_tokens(db: AsyncSession, user: User) -> TokenResponse:
    access, expires_in = create_access_token(user.id, user.role, username=user.username)
    raw_refresh, refresh_digest, refresh_expires = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_digest,
            expires_at=refresh_expires,
        )
    )
    await db.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=expires_in,
        user={
            **user.public_dict(),
            "permissions": current_permissions(user),
        },
    )


def _client_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.lower()}"


# ------------------------------------------------------------------ endpoints


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    limiter = limiters.get("login", settings.login_rate_limit_per_minute, 60.0)
    key = _client_key(request, payload.username)
    if not limiter.allow(key):
        raise AppError(
            "too_many_attempts",
            "登录尝试过于频繁，请稍后再试",
            status_code=429,
        )

    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    # 用户不存在与密码错误返回同一个错误，避免账号枚举
    if user is None or not verify_password(payload.password, user.password_hash):
        await record_audit(db, user_id=None, action="login_failed", detail={"username": payload.username})
        raise AppError("invalid_credentials", "用户名或密码错误", status_code=401)
    if not user.is_active:
        raise AppError("user_disabled", "账号已被停用", status_code=403)

    user.last_login_at = datetime.utcnow()
    await db.commit()
    tokens = await _issue_tokens(db, user)
    await record_audit(db, user_id=user.id, action="login", detail={"role": user.role})
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    digest = hash_refresh_token(payload.refresh_token)
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == digest))
    ).scalar_one_or_none()
    if row is None or row.revoked:
        raise AppError("invalid_refresh_token", "刷新令牌无效，请重新登录", status_code=401)
    if row.expires_at <= datetime.utcnow():
        row.revoked = True
        await db.commit()
        raise AppError("refresh_token_expired", "刷新令牌已过期，请重新登录", status_code=401)

    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AppError("user_disabled", "账号已被停用", status_code=403)

    # 轮换：旧 token 立刻作废，重放会被拒绝
    row.revoked = True
    await db.commit()
    return await _issue_tokens(db, user)


@router.post("/logout")
async def logout(
    payload: RefreshRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    digest = hash_refresh_token(payload.refresh_token)
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == digest))
    ).scalar_one_or_none()
    if row is not None and row.user_id == user.id:
        row.revoked = True
        await db.commit()
    await record_audit(db, user_id=user.id, action="logout")
    return {"status": "ok"}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {**user.public_dict(), "permissions": current_permissions(user)}


# ------------------------------------------------------------------ user management


@router.get("/users")
async def list_users(
    _: User = Depends(require("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return {"items": [u.public_dict() for u in users]}


@router.post("/users", status_code=201)
async def create_user(
    payload: UserCreateRequest,
    current: User = Depends(require("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_role(payload.role):
        raise AppError("invalid_role", f"角色必须是 {', '.join(ALL_ROLES)}", status_code=400)
    exists = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if exists:
        raise AppError("username_taken", "用户名已存在", status_code=409)
    user = User(
        username=payload.username,
        display_name=payload.display_name or payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await record_audit(
        db, user_id=current.id, action="user_create", detail={"username": user.username, "role": user.role}
    )
    return user.public_dict()


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    current: User = Depends(require("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AppError("user_not_found", "用户不存在", status_code=404)

    if payload.role is not None:
        if not is_valid_role(payload.role):
            raise AppError("invalid_role", f"角色必须是 {', '.join(ALL_ROLES)}", status_code=400)
        if user.id == current.id and payload.role != user.role:
            raise AppError("cannot_change_own_role", "不能修改自己的角色", status_code=400)
        user.role = payload.role
    if payload.is_active is not None:
        if user.id == current.id and not payload.is_active:
            raise AppError("cannot_disable_self", "不能停用自己的账号", status_code=400)
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.display_name is not None:
        user.display_name = payload.display_name
    await db.commit()
    await record_audit(db, user_id=current.id, action="user_update", detail={"target": user.id})
    return user.public_dict()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current: User = Depends(require("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AppError("user_not_found", "用户不存在", status_code=404)
    if user.id == current.id:
        raise AppError("cannot_delete_self", "不能删除自己的账号", status_code=400)
    # 软删除：保留历史会话与审计的外键含义
    user.is_active = False
    await db.commit()
    await record_audit(db, user_id=current.id, action="user_delete", detail={"target": user.id})
    return {"status": "deleted"}


@router.get("/permissions")
async def permission_matrix(user: User = Depends(get_current_user)):
    """给前端渲染用：声明式列出角色所需权限点是否具备。"""
    from app.services.auth import PERMISSIONS

    return {
        "roles": {
            role: sorted(perms) for role, perms in PERMISSIONS.items()
        },
        "current": {"role": user.role, "permissions": current_permissions(user)},
        "sql_write_allowed": role_has(user.role, "sql:write"),
    }
