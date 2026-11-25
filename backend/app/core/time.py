"""时间工具。

SQLite 的 `CURRENT_TIMESTAMP` 存的是 UTC 但**不带时区**，直接 isoformat 出去，
前端 `new Date()` 会当成本地时间，出现 8 小时偏差。所有对外时间统一走这里。
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def utc_now_naive() -> datetime:
    """用于写入库里那种不带时区的 DateTime 列。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
