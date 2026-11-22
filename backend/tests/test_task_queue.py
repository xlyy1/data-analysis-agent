"""后台任务队列测试：状态流转、失败重试上限、重启恢复、超时。"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.task import FAILED, QUEUED, RUNNING, SUCCEEDED, BackgroundTask
from app.services.task_queue import TaskQueue, register_handler


@pytest.fixture()
async def factory(tmp_path):
    db = tmp_path / "tasks.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield f
    finally:
        await engine.dispose()


async def _wait_terminal(queue: TaskQueue, task_id: str, timeout: float = 6.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        task = await queue.get(task_id)
        if task and task["status"] in (SUCCEEDED, FAILED):
            return task
        await asyncio.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内进入终态")


@pytest.mark.asyncio
async def test_task_succeeds_and_records_result(factory):
    calls: list[dict] = []

    @register_handler("t_ok")
    async def ok(payload):
        calls.append(payload)
        return {"doubled": payload.get("n", 0) * 2}

    queue = TaskQueue(factory, workers=2, max_retries=1, timeout_seconds=5)
    await queue.start()
    try:
        task_id = await queue.submit("t_ok", {"n": 21})
        task = await _wait_terminal(queue, task_id)
        assert task["status"] == SUCCEEDED
        assert task["result"] == {"doubled": 42}
        assert task["attempts"] == 1
        assert calls == [{"n": 21}]
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_task_retries_then_fails(factory):
    attempts: list[int] = []

    @register_handler("t_boom")
    async def boom(payload):
        attempts.append(1)
        raise RuntimeError("故意失败")

    queue = TaskQueue(factory, workers=1, max_retries=1, timeout_seconds=5)
    await queue.start()
    try:
        task_id = await queue.submit("t_boom")
        task = await _wait_terminal(queue, task_id)
        assert task["status"] == FAILED
        # max_retries=1 -> 首次 + 重试 1 次
        assert task["attempts"] == 2
        assert len(attempts) == 2
        assert "故意失败" in (task["error"] or "")
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_task_timeout_is_capped(factory):
    @register_handler("t_slow")
    async def slow(payload):
        await asyncio.sleep(5)
        return {}

    queue = TaskQueue(factory, workers=1, max_retries=0, timeout_seconds=0.2)
    await queue.start()
    try:
        task_id = await queue.submit("t_slow")
        task = await _wait_terminal(queue, task_id)
        assert task["status"] == FAILED
        assert "TimeoutError" in (task["error"] or "") or "timed out" in (task["error"] or "")
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_recover_pending_reruns_queued_task(factory):
    @register_handler("t_recover")
    async def recover(payload):
        return {"recovered": True}

    async with factory() as session:
        row = BackgroundTask(kind="t_recover", payload_json="{}", status=QUEUED)
        session.add(row)
        await session.commit()
        task_id = row.id

    queue = TaskQueue(factory, workers=1, max_retries=0, timeout_seconds=5)
    await queue.start()  # start 内部会 recover_pending
    try:
        task = await _wait_terminal(queue, task_id)
        assert task["status"] == SUCCEEDED
        assert task["result"] == {"recovered": True}
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_recover_pending_resets_running_and_reruns(factory):
    """重启时 running 的任务要归位到 queued 并重新执行。"""

    @register_handler("t_recover_running")
    async def recover_running(payload):
        return {"done": True}

    async with factory() as session:
        row = BackgroundTask(kind="t_recover_running", payload_json="{}", status=RUNNING, attempts=1)
        session.add(row)
        await session.commit()
        task_id = row.id

    queue = TaskQueue(factory, workers=1, max_retries=0, timeout_seconds=5)
    await queue.start()
    try:
        task = await _wait_terminal(queue, task_id)
        assert task["status"] == SUCCEEDED
        assert task["attempts"] == 2  # 跑过一次（attempts=1）+ 恢复后再跑
        assert task["result"] == {"done": True}
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_unknown_kind_fails(factory):
    queue = TaskQueue(factory, workers=1, max_retries=0, timeout_seconds=5)
    await queue.start()
    try:
        task_id = await queue.submit("t_not_registered")
        task = await _wait_terminal(queue, task_id)
        assert task["status"] == FAILED
        assert "未注册" in (task["error"] or "")
    finally:
        await queue.stop()
