"""进程内后台任务队列：提交即返回，worker 池消费，状态落库可查。

为什么不用现成的 Celery/Redis：这个项目是单机部署，长任务（报表生成、批量取数）
一天几十个，起一个 Redis 只为排队不划算。这里用 asyncio.Queue + 固定 worker 池，
任务状态写进 SQLite 的 background_tasks 表，进程重启后能把没跑完的重新捡起来。

三条规则：
1. 任务不丢：先落库（queued）再入队；入队失败就留 queued，重启时 recover_pending 会捡。
2. 失败有上限：attempts 超过 max_retries 置 failed，不无限重试。
3. 单任务有超时：asyncio.wait_for 硬切，避免一个卡住的任务占着 worker。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.task import (
    FAILED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    BackgroundTask,
)

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[dict]]
_HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str):
    """注册任务处理器：@register_handler("report") 挂在 async 函数上。"""

    def wrapper(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return wrapper


def handler_for(kind: str) -> Handler | None:
    return _HANDLERS.get(kind)


class TaskQueue:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        workers: int | None = None,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        if session_factory is None:
            from app.database import async_session as default_factory

            session_factory = default_factory
        self._session_factory = session_factory
        self._workers = workers if workers is not None else settings.task_workers
        self._max_retries = max_retries if max_retries is not None else settings.task_max_retries
        self._timeout = timeout_seconds if timeout_seconds is not None else settings.task_timeout_seconds
        self._queue: asyncio.Queue[str] | None = None
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        if self._running:
            return
        self._queue = asyncio.Queue()
        self._running = True
        for i in range(self._workers):
            self._tasks.append(asyncio.create_task(self._worker(i), name=f"task-worker-{i}"))
        await self.recover_pending()

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    # ---------- 对外接口 ----------

    async def submit(self, kind: str, payload: dict | None = None) -> str:
        """落库后入队，返回任务 id；入队失败任务仍是 queued，重启可恢复。"""
        async with self._session_factory() as session:
            task = BackgroundTask(
                kind=kind,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
                status=QUEUED,
            )
            session.add(task)
            await session.commit()
            task_id = task.id

        if self._queue is not None:
            await self._queue.put(task_id)
        return task_id

    async def get(self, task_id: str) -> dict | None:
        async with self._session_factory() as session:
            row = await session.get(BackgroundTask, task_id)
            return _to_dict(row) if row else None

    async def list(self, status: str | None = None, limit: int = 20) -> list[dict]:
        async with self._session_factory() as session:
            stmt = select(BackgroundTask)
            if status:
                stmt = stmt.where(BackgroundTask.status == status)
            stmt = stmt.order_by(BackgroundTask.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_dict(r) for r in rows]

    async def recover_pending(self) -> int:
        """进程重启后把 queued/running 的任务重新入队，避免任务悬空。

        恢复是启动路径，一次批量 UPDATE 把 running 归位，避免逐行提交。
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(BackgroundTask).where(BackgroundTask.status.in_([QUEUED, RUNNING]))
                )
            ).scalars().all()
            if not rows:
                return 0
            ids = [row.id for row in rows]
            await session.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id.in_(ids), BackgroundTask.status == RUNNING)
                .values(status=QUEUED)
            )
            await session.commit()

        if self._queue is not None:
            for task_id in ids:
                await self._queue.put(task_id)
        logger.info("恢复未完成任务 %d 个", len(ids))
        return len(ids)

    # ---------- 执行 ----------

    async def _worker(self, index: int) -> None:
        assert self._queue is not None
        while self._running:
            try:
                task_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._run_one(task_id)
            except Exception:  # noqa: BLE001
                logger.exception("任务执行异常 task=%s worker=%d", task_id, index)
            finally:
                self._queue.task_done()

    async def _run_one(self, task_id: str) -> None:
        async with self._session_factory() as session:
            task = await session.get(BackgroundTask, task_id)
            if task is None or task.status in (SUCCEEDED, FAILED):
                return
            task.status = RUNNING
            task.attempts += 1
            attempts = task.attempts
            kind = task.kind
            payload = json.loads(task.payload_json) if task.payload_json else {}
            await session.commit()

        handler = handler_for(kind)
        try:
            if handler is None:
                raise LookupError(f"未注册的任务类型：{kind}")
            result = await asyncio.wait_for(handler(payload), timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            await self._finish(task_id, error=f"{type(exc).__name__}: {exc}", attempts=attempts)
            return

        await self._finish(task_id, result=result, attempts=attempts)

    async def _finish(
        self,
        task_id: str,
        *,
        result: dict | None = None,
        error: str | None = None,
        attempts: int = 0,
    ) -> None:
        async with self._session_factory() as session:
            task = await session.get(BackgroundTask, task_id)
            if task is None:
                return
            if error is None:
                task.status = SUCCEEDED
                task.result_json = json.dumps(result or {}, ensure_ascii=False)
                task.error = None
            elif attempts <= self._max_retries:
                # 还有重试额度：回到 queued，重新入队
                task.status = QUEUED
                task.error = error
                await session.commit()
                if self._queue is not None:
                    await self._queue.put(task_id)
                return
            else:
                task.status = FAILED
                task.error = error
            await session.commit()


def _to_dict(row: BackgroundTask) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "attempts": row.attempts,
        "payload": json.loads(row.payload_json) if row.payload_json else {},
        "result": json.loads(row.result_json) if row.result_json else None,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# 全局单例：应用启动时 start()，关闭时 stop()
task_queue = TaskQueue()
