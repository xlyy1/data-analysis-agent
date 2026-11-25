"""审计事件：把"谁在什么时候对什么做了什么"落库。

写失败绝不影响主流程（审计是旁路），但会打 warning 日志。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log import OperationLog

logger = logging.getLogger(__name__)


async def record_audit(
    db: AsyncSession,
    *,
    user_id: str | None,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        db.add(
            OperationLog(
                user_id=user_id,
                action=action,
                detail=json.dumps(detail or {}, ensure_ascii=False, default=str),
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - 审计旁路
        logger.warning("audit write failed action=%s", action, exc_info=True)
