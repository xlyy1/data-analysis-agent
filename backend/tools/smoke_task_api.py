"""端到端烟测：手动进入 app 的 lifespan（建表 + 启动队列）-> POST /api/tasks -> 轮询到 succeeded。

用临时 DB 文件，不污染 backend/data/agent.db。
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("NO_PROXY", "*")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tmp = Path(tempfile.mkdtemp(prefix="smoke-"))
db = tmp / "smoke.db"

import app.database as database  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

database.DB_FILE = str(db)
database.engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
database.async_session = async_sessionmaker(database.engine, expire_on_commit=False)

import app.services.task_queue as tq  # noqa: E402

tq.task_queue._session_factory = database.async_session

import httpx  # noqa: E402

from app.main import app  # noqa: E402


async def main() -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post("/api/tasks", json={"kind": "echo", "payload": {"hello": "world"}})
            print("submit:", resp.status_code, resp.json())
            task_id = resp.json()["id"]

            final = None
            for _ in range(200):
                r = await client.get(f"/api/tasks/{task_id}")
                body = r.json()
                if body["status"] in ("succeeded", "failed"):
                    final = body
                    break
                await asyncio.sleep(0.05)

            print("final:", json.dumps(final, ensure_ascii=False) if final else "TIMEOUT")
            listing = await client.get("/api/tasks?limit=5")
            print("list:", listing.status_code, len(listing.json()["items"]))
            bad = await client.post("/api/tasks", json={"kind": "nope", "payload": {}})
            print("unknown kind:", bad.status_code, bad.json())

            ok = (
                final is not None
                and final["status"] == "succeeded"
                and final["result"]["echo"] == {"hello": "world"}
                and final["attempts"] == 1
                and bad.status_code == 400
            )
            return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
