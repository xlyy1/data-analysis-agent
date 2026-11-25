"""SQL 安全校验的只读调试接口。

只做校验、**不执行**：给运维/面试演示一个可以亲眼看到"这条 SQL 为什么被拒"的入口，
同时不在 API 层多开一个执行面。真正的执行闸在 `app.agent.nodes.execute`。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import require
from app.config import get_settings
from app.models.user import User
from app.services.sql_policy import guard_sql

router = APIRouter(prefix="/api/sql", tags=["sql"])


class SqlCheckRequest(BaseModel):
    sql: str = Field(max_length=200_000)
    allow_write: bool = False


@router.post("/validate")
async def validate_sql(
    payload: SqlCheckRequest,
    user: User = Depends(require("sql:write")),
):
    """返回只读策略对这段 SQL 的判定（通过/拒绝原因/自动补的 LIMIT）。"""
    settings = get_settings()
    decision = guard_sql(
        payload.sql,
        max_chars=settings.sql_max_chars,
        default_limit=settings.sql_default_limit,
        allow_write=payload.allow_write and settings.sql_allow_write_for_admin,
    )
    return {
        "allowed": decision.ok,
        "code": decision.code or "ok",
        "reason": decision.reason,
        "normalized_sql": decision.sql,
        "applied_limit": decision.applied_limit,
        "policy": {
            "max_chars": settings.sql_max_chars,
            "default_limit": settings.sql_default_limit,
            "write_allowed": settings.sql_allow_write_for_admin,
            "role": user.role,
        },
    }
