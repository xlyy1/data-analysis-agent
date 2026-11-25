"""用户与刷新令牌模型。

角色只有三级，够中小商家用：
- admin   管理员：用户管理 + 数据源增删改 + 全部读
- analyst 分析师：自己创建数据源、跑分析、出报告
- viewer  只读：能看对话/结果，不能改数据源，不能执行写 SQL
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

ROLE_ADMIN = "admin"
ROLE_ANALYST = "analyst"
ROLE_VIEWER = "viewer"

ALL_ROLES = (ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    def public_dict(self) -> dict:
        from app.core.time import utc_iso

        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": bool(self.is_active),
            "created_at": utc_iso(self.created_at),
            "last_login_at": utc_iso(self.last_login_at),
        }


class RefreshToken(Base):
    """刷新令牌只存哈希，泄露数据库也拿不到可用 token。"""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("idx_refresh_user", "user_id", "revoked"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
