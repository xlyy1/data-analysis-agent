"""认证依赖：从 Authorization: Bearer 取用户，并按权限点鉴权。"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.database import get_db
from app.models.user import User
from app.services.auth import decode_access_token, permissions_for, role_has

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(message: str = "未登录或登录已过期") -> AppError:
    return AppError("unauthorized", message, status_code=401)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as error:
        raise _unauthorized("凭证无效") from error

    user = (
        await db.execute(select(User).where(User.id == payload["sub"]))
    ).scalar_one_or_none()
    if user is None:
        raise _unauthorized("用户不存在")
    if not user.is_active:
        raise AppError("user_disabled", "账号已被停用", status_code=403)
    request.state.user_id = user.id
    request.state.user_role = user.role
    return user


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await get_current_user(request, credentials, db)
    except AppError:
        return None


def require(*permissions: str):
    """用法：`dependencies=[Depends(require("datasource:write"))]`。"""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        missing = [p for p in permissions if not role_has(user.role, p)]
        if missing:
            raise AppError(
                "forbidden",
                f"当前角色（{user.role}）无权执行该操作",
                status_code=403,
                details={"required": list(permissions), "missing": missing},
            )
        return user

    return dependency


def current_permissions(user: User) -> list[str]:
    return sorted(permissions_for(user.role))
