"""API 与任务服务的集成测试：API 只做转发，任务服务真正执行。

用 httpx.ASGITransport 把两个应用接起来，不占端口，但走的是真实的 HTTP 语义。
"""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.database as database
import app.services.task_queue as tq
from app.database import Base
from app.services.task_service_client import TaskServiceClient


@pytest.fixture()
async def temp_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'svc.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "async_session", factory)
    monkeypatch.setattr(tq.task_queue, "_session_factory", factory)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _wait_done(client, api_base: str, task_id: str, timeout: float = 6.0) -> dict:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        response = await client.get(f"{api_base}/api/tasks/{task_id}")
        body = response.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("任务未在超时内进入终态")


@pytest.mark.asyncio
async def test_api_proxies_to_task_service(temp_db, monkeypatch):
    from worker_service.main import app as worker_app
    import app.api.tasks as tasks_api

    worker_transport = httpx.ASGITransport(app=worker_app)
    monkeypatch.setattr(
        tasks_api,
        "_client",
        lambda: TaskServiceClient("http://task-service.test", transport=worker_transport, retries=0),
    )

    async with worker_app.router.lifespan_context(worker_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=__import__("app.main", fromlist=["app"]).app),
            base_url="http://api.test",
        ) as client:
            submitted = await client.post("/api/tasks", json={"kind": "echo", "payload": {"x": 1}})
            assert submitted.status_code == 200
            task_id = submitted.json()["id"]

            final = await _wait_done(client, "http://api.test", task_id)
            assert final["status"] == "succeeded"
            assert final["result"]["echo"] == {"x": 1}

            listing = await client.get("/api/tasks?limit=5")
            assert listing.status_code == 200
            assert len(listing.json()["items"]) >= 1


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected_not_502(temp_db, monkeypatch):
    from worker_service.main import app as worker_app
    import app.api.tasks as tasks_api

    worker_transport = httpx.ASGITransport(app=worker_app)
    monkeypatch.setattr(
        tasks_api,
        "_client",
        lambda: TaskServiceClient("http://task-service.test", transport=worker_transport, retries=0),
    )

    async with worker_app.router.lifespan_context(worker_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=__import__("app.main", fromlist=["app"]).app),
            base_url="http://api.test",
        ) as client:
            response = await client.post("/api/tasks", json={"kind": "nope", "payload": {}})
            assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_returns_502_when_service_unreachable(temp_db, monkeypatch):
    import app.api.tasks as tasks_api

    def dead(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(
        tasks_api,
        "_client",
        lambda: TaskServiceClient(
            "http://task-service.test", transport=httpx.MockTransport(dead), retries=0, timeout=0.5
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=__import__("app.main", fromlist=["app"]).app),
        base_url="http://api.test",
    ) as client:
        response = await client.post("/api/tasks", json={"kind": "echo", "payload": {}})
        assert response.status_code == 502
        assert "任务服务不可用" in response.json()["detail"]
