"""启动期数据准备：管理员账号 + 演示数据。

两件事都只在"库里没有"时执行，因此可以安全地在每次启动时调用。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import ROLE_ADMIN, User
from app.services.auth import hash_password

logger = logging.getLogger(__name__)


async def ensure_bootstrap_admin(db: AsyncSession) -> User | None:
    """用户表为空时创建初始管理员，避免系统装好以后没人能登录。"""
    settings = get_settings()
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if count:
        return None
    admin = User(
        username=settings.bootstrap_admin_username,
        display_name="系统管理员",
        password_hash=hash_password(settings.bootstrap_admin_password),
        role=ROLE_ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    logger.warning(
        "已创建初始管理员 username=%s，请立即修改默认密码",
        settings.bootstrap_admin_username,
    )
    return admin
