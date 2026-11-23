"""任务服务冒烟：真起一个 uvicorn 进程（真实 HTTP），验证健康检查与任务生命周期。

跑法：
    python tools/smoke_task_service.py
退出码 0 表示成功。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("NO_PROXY", "*")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

PORT = 8021
BASE = f"http://127.0.0.1:{PORT}"


def _prepare_db() -> str:
    """给任务服务换一个临时库，避免污染开发数据。"""
    db = Path(tempfile.mkdtemp(prefix="smoke-worker-")) / "tasks.db"

    import app.database as database

    database.DB_FILE = str(db)
    database.engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    database.async_session = async_sessionmaker(database.engine, expire_on_commit=False)

    import app.services.task_queue as tq

    tq.task_queue._session_factory = database.async_session
    return str(db)


async def _run() -> int:
    from worker_service.main import app as worker_app

    config = uvicorn.Config(worker_app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while time.time() < deadline and not server.started:
        await asyncio.sleep(0.1)
    if not server.started:
        print("FAIL: 任务服务没起来")
        return 1
    print("worker started on", BASE)

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            health = await client.get(f"{BASE}/healthz")
            print("healthz:", health.status_code, health.json())
            assert health.status_code == 200

            submitted = await client.post(f"{BASE}/tasks", json={"kind": "echo", "payload": {"n": 7}})
            print("submit:", submitted.status_code, submitted.json())
            assert submitted.status_code == 200
            task_id = submitted.json()["id"]

            final = None
            for _ in range(100):
                body = (await client.get(f"{BASE}/tasks/{task_id}")).json()
                if body["status"] in ("succeeded", "failed"):
                    final = body
                    break
                await asyncio.sleep(0.05)
            print("final:", json.dumps(final, ensure_ascii=False) if final else "TIMEOUT")
            assert final and final["status"] == "succeeded"
            assert final["result"]["echo"] == {"n": 7}

            bad = await client.post(f"{BASE}/tasks", json={"kind": "no_such_kind", "payload": {}})
            print("unknown kind:", bad.status_code)
            assert bad.status_code == 400

            missing = await client.get(f"{BASE}/tasks/not-exist")
            print("missing task:", missing.status_code)
            assert missing.status_code == 404

        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    _prepare_db()
    sys.exit(asyncio.run(_run()))
