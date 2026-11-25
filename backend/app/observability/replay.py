"""按 task_id 回放一条 Agent 执行链路。

用法：
    python -m app.observability.replay <task_id>
    python -m app.observability.replay --list 20
    python -m app.observability.replay <task_id> --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.observability.trace import get_db_path, load_trace, summarize
from app.core.sqlite import sqlite_connection


def list_tasks(limit: int = 20, db_path: Path | None = None) -> list[dict]:
    path = db_path or get_db_path()
    if not Path(path).exists():
        return []
    with sqlite_connection(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT task_id, COUNT(*) AS events, "
            "       SUM(duration_ms) AS total_ms, MAX(started_at) AS last_at "
            "FROM trace_events GROUP BY task_id ORDER BY last_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回放 Agent 执行链路")
    parser.add_argument("task_id", nargs="?", help="task_id；省略时配合 --list 使用")
    parser.add_argument("--list", type=int, default=0, help="列出最近 N 条 task")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出原始事件")
    parser.add_argument("--db", type=str, default="", help="自定义 traces.db 路径")
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else None

    if args.list:
        tasks = list_tasks(args.list, db_path)
        if not tasks:
            print("(no traces)")
            return 0
        for t in tasks:
            print(f"{t['task_id']}  events={t['events']:<3} total={t['total_ms'] or 0:.0f}ms")
        return 0

    if not args.task_id:
        parser.error("需要 task_id，或使用 --list N")

    events = load_trace(args.task_id, db_path)
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        print(summarize(events))
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(main())
