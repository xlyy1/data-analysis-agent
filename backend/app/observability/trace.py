"""Agent 执行链路追踪。

每个节点执行前后记录一条结构化事件（task_id、节点名、状态、耗时、关键字段变更、
错误信息），落 SQLite，供 `app.observability.replay` 按 task_id 回放整条链路。

设计取舍：
- 只记录「摘要 + 关键字段」，不落完整 state，避免把用户数据与 SQL 结果重复存一份；
- 独立 traces.db，不与应用库混用，删掉不影响业务数据；
- 追踪失败绝不影响主流程（record 内部吞掉异常并走 logger）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import get_settings
from app.core.sqlite import sqlite_connection

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    seq         INTEGER NOT NULL,
    node        TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    started_at  REAL    NOT NULL,
    duration_ms REAL    NOT NULL,
    fields      TEXT    NOT NULL DEFAULT '{}',
    error       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trace_task ON trace_events(task_id, seq);
"""

# 每个节点执行后值得记录的字段：只取摘要性字段，不落 messages / query_result_json 这类大对象
NODE_FIELDS: dict[str, tuple[str, ...]] = {
    "understand_intent": ("analysis_type", "needs_clarification", "clarification_question"),
    "generate_query": ("generated_sql", "sql_needs_confirmation", "sql_retry_count"),
    "execute_query": ("empty_result", "sql_retry_count", "error"),
    "analyze_results": ("analysis_type", "analysis_summary", "result_warnings"),
    "diagnose": ("diagnosis_causes", "diagnosis_suggestions"),
    "generate_visualization": ("chart_config_json",),
    "format_response": ("final_response",),
}

_MAX_FIELD_CHARS = 400


def get_db_path() -> Path:
    """追踪库路径；配置为相对路径时按 backend 目录解析，便于本地与测试各自隔离。"""
    settings = get_settings()
    path = Path(settings.trace_db_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db(db_path: Path | None = None) -> None:
    path = db_path or get_db_path()
    with sqlite_connection(path) as conn:
        conn.executescript(SCHEMA)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def ensure_trace_id(state: dict[str, Any]) -> str:
    """一次请求内所有节点共用同一个 task_id。"""
    trace_id = state.get("trace_id")
    if not trace_id:
        trace_id = new_trace_id()
        state["trace_id"] = trace_id
    return trace_id


def record(
    task_id: str,
    node: str,
    status: str,
    started_at: float,
    duration_ms: float,
    fields: dict[str, Any] | None = None,
    error: str = "",
    db_path: Path | None = None,
) -> None:
    """写一条事件。任何异常都只记日志，不影响主流程。"""
    try:
        path = db_path or get_db_path()
        init_db(path)
        with sqlite_connection(path) as conn:
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO trace_events "
                "(task_id, seq, node, status, started_at, duration_ms, fields, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    seq,
                    node,
                    status,
                    started_at,
                    round(duration_ms, 2),
                    json.dumps(fields or {}, ensure_ascii=False, default=str),
                    error,
                ),
            )
    except Exception:  # noqa: BLE001 - 追踪不能拖垮业务
        logger.warning("trace record failed: node=%s task_id=%s", node, task_id, exc_info=True)


def _summarize(value: Any) -> Any:
    """把字段值压成可读摘要：长字符串截断，列表只保留首项与长度。"""
    if isinstance(value, str) and len(value) > _MAX_FIELD_CHARS:
        return value[:_MAX_FIELD_CHARS] + f"...({len(value)} chars)"
    if isinstance(value, (list, tuple)):
        head = [_summarize(v) for v in value[:2]]
        return {"count": len(value), "head": head} if len(value) > 2 else head
    if isinstance(value, dict) and len(value) > 6:
        return {"keys": list(value)[:6], "count": len(value)}
    return value


def extract_fields(node: str, state: dict[str, Any]) -> dict[str, Any]:
    names = NODE_FIELDS.get(node, ())
    return {name: _summarize(state.get(name)) for name in names if state.get(name) not in (None, "", [], {})}


def traced(node: str) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[dict]]]:
    """包一层节点：记录耗时与关键字段，异常时记录 error 并把异常继续抛出。"""

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        @wraps(fn)
        async def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            if not get_settings().trace_enabled:
                return await fn(state, *args, **kwargs)

            task_id = ensure_trace_id(state)
            started_at = time.time()
            t0 = time.perf_counter()
            try:
                result = await fn(state, *args, **kwargs)
            except Exception as exc:
                session = task_id
                record(
                    session,
                    node,
                    "error",
                    started_at,
                    (time.perf_counter() - t0) * 1000,
                    fields={"args": str(exc)[:200]},
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            duration = (time.perf_counter() - t0) * 1000
            merged = result if isinstance(result, dict) else state
            merged.setdefault("trace_id", task_id)
            record(task_id, node, "ok", started_at, duration, fields=extract_fields(node, merged))
            return result

        return wrapper

    return decorator


def load_trace(task_id: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = db_path or get_db_path()
    if not Path(path).exists():
        return []
    with sqlite_connection(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM trace_events WHERE task_id = ? ORDER BY seq", (task_id,)
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["fields"] = json.loads(item["fields"] or "{}")
        events.append(item)
    return events


def summarize(events: list[dict[str, Any]]) -> str:
    """把事件列表渲染成一条可读时间线，供回放 CLI 与测试使用。"""
    if not events:
        return "(no trace events)"
    lines = [
        f"task {events[0]['task_id']} · {len(events)} events · "
        f"total {sum(e['duration_ms'] for e in events):.0f} ms"
    ]
    for e in events:
        mark = "ok " if e["status"] == "ok" else "ERR"
        lines.append(f"  [{mark}] {e['seq']:>2} {e['node']:<22} {e['duration_ms']:>8.1f} ms")
        if e["fields"]:
            lines.append(f"        {json.dumps(e['fields'], ensure_ascii=False)}")
        if e["error"]:
            lines.append(f"        error: {e['error']}")
    return "\n".join(lines)
