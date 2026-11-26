"""审计查询 API。

`operation_logs` 一直在写（登录、改数据源、生成报告、删除会话、调度执行…），
但此前没有任何读取入口，权限点 `audit:read` 也成了摆设。这个路由把它接出来：

- 只对 `audit:read` 开放（目前= admin）；
- 支持按 action / user_id / 起始时间过滤 + 分页；
- 返回前对 detail 里的敏感键（password/token/secret…）做遮蔽，
  审计记录本身不应该成为二次泄露源。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.core.time import utc_iso
from app.database import get_db
from app.models.log import OperationLog
from app.models.user import User

router = APIRouter(prefix="/api/audit", tags=["audit"])

# detail 里出现这些键名就遮蔽（大小写不敏感，子串匹配）
SENSITIVE_HINTS = ("password", "passwd", "secret", "token", "api_key", "apikey", "authorization")
MASK = "***"


def _mask_value(key: str, value):
    if isinstance(key, str) and any(hint in key.lower() for hint in SENSITIVE_HINTS) and value not in (None, ""):
        return MASK
    return value


def _sanitize(detail) -> dict:
    """递归遮蔽敏感键；非 dict 原样返回，保证响应可 JSON 化。"""
    if isinstance(detail, dict):
        return {key: _sanitize(_mask_value(key, value)) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_sanitize(item) for item in detail]
    return detail


def _parse_detail(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"_raw": str(raw)[:200]}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def to_item(row: OperationLog) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "action": row.action,
        "detail": _sanitize(_parse_detail(row.detail)),
        "created_at": utc_iso(row.created_at),
    }


@router.get("")
async def list_audit(
    _: User = Depends(require("audit:read")),
    db: AsyncSession = Depends(get_db),
    action: str | None = Query(default=None, description="按动作精确过滤，如 datasource_create"),
    user_id: str | None = Query(default=None, description="按操作者过滤"),
    since: datetime | None = Query(default=None, description="起始时间（ISO8601），含边界"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    conditions = []
    if action:
        conditions.append(OperationLog.action == action)
    if user_id:
        conditions.append(OperationLog.user_id == user_id)
    if since is not None:
        # 库里存的是 naive UTC，带时区的入参先换算
        moment = since.astimezone(timezone.utc).replace(tzinfo=None) if since.tzinfo else since
        conditions.append(OperationLog.created_at >= moment)

    base = select(OperationLog)
    counter = select(func.count()).select_from(OperationLog)
    if conditions:
        base = base.where(*conditions)
        counter = counter.where(*conditions)

    total = (await db.execute(counter)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return {
        "items": [to_item(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {"action": action, "user_id": user_id, "since": since.isoformat() if since else None},
    }


@router.get("/actions")
async def list_actions(
    _: User = Depends(require("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    """动作清单 + 次数，给前端下拉框用。"""
    rows = (
        await db.execute(
            select(OperationLog.action, func.count().label("count"))
            .group_by(OperationLog.action)
            .order_by(func.count().desc())
        )
    ).all()
    return {"items": [{"action": action, "count": count} for action, count in rows]}


@router.get("/{log_id}")
async def get_audit_log(
    log_id: str,
    _: User = Depends(require("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(OperationLog).where(OperationLog.id == log_id))).scalar_one_or_none()
    if row is None:
        from app.core.errors import AppError

        raise AppError("audit_not_found", "审计记录不存在", status_code=404)
    return to_item(row)
