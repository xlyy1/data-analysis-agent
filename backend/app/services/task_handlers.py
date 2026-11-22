"""注册到任务队列的处理器。

目前只挂真实有用的两个：
- trace_cleanup：清理过期的执行追踪（trace_events 只保留最近 N 天）
- echo：联调用，原样返回 payload 并带上耗时
"""

from __future__ import annotations

import sqlite3
import time

from app.observability import trace
from app.services.task_queue import register_handler


@register_handler("trace_cleanup")
async def trace_cleanup(payload: dict) -> dict:
    """删除 N 天前的 trace 事件，返回删了多少条。"""
    days = int(payload.get("days", 30))
    cutoff = time.time() - days * 86400
    path = trace.get_db_path()
    with sqlite3.connect(path) as conn:
        cursor = conn.execute("DELETE FROM trace_events WHERE started_at < ?", (cutoff,))
        deleted = cursor.rowcount or 0
        conn.commit()
    return {"deleted": deleted, "days": days}


@register_handler("echo")
async def echo(payload: dict) -> dict:
    return {"echo": payload, "at": time.time()}
