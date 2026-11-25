"""定时分析调度器。

运行位置：跑在 task-worker 进程里（它持有任务队列，提交不用走 HTTP）。
API 进程只提供 schedule 的 CRUD 和"立即执行"，执行一律落到任务队列。

幂等设计（这是 P5 的核心）：
- `schedule_runs(schedule_id, scheduled_for)` 唯一约束 —— 同一个计划在同一个
  计划时刻只可能插入一条 run，重复 tick / 多副本 / 重启重放都会被数据库挡住；
- 插入成功才更新 next_run_at 并提交任务，所以不会出现"时间推了但没跑"；
- handler 里再判断一次 `run.status == succeeded`，重复投递直接跳过。

失败隔离：单个计划失败只影响它自己（consecutive_failures 累计，连续 3 次自动停用），
同一轮里其它计划照常执行。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.schedule import AnalysisSchedule, ScheduleRun

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 3


def compute_next_run(now: datetime, interval_minutes: int) -> datetime:
    return now + timedelta(minutes=max(1, int(interval_minutes)))


async def claim_due_schedules(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[str]:
    """抢占到期的计划，返回新建的 run id 列表。

    调用方负责把这些 run id 提交到任务队列；抢占本身已落库，所以即使提交失败
    也不会重复执行（run 会停在 queued，由任务队列的恢复机制接手）。
    """
    now = now or datetime.utcnow()
    claimed: list[str] = []

    async with session_factory() as session:
        due = (
            await session.execute(
                select(AnalysisSchedule)
                .where(
                    AnalysisSchedule.enabled == True,  # noqa: E712
                    AnalysisSchedule.next_run_at.isnot(None),
                    AnalysisSchedule.next_run_at <= now,
                )
                .order_by(AnalysisSchedule.next_run_at)
                .limit(limit)
            )
        ).scalars().all()

        for schedule in due:
            slot = schedule.next_run_at
            interval = schedule.interval_minutes
            schedule_id = schedule.id
            run = ScheduleRun(
                schedule_id=schedule_id,
                scheduled_for=slot,
                status="queued",
            )
            session.add(run)
            try:
                await session.commit()
            except IntegrityError:
                # 这个时刻已经被别人抢到（另一个 tick / 另一个副本）：
                # 必须把 next_run_at 往前推，否则该计划每轮都会撞同一个唯一键。
                # 用独立 UPDATE 而不是改 ORM 属性 —— rollback 之后属性已过期，
                # 异步会话里访问过期属性会抛 MissingGreenlet。
                await session.rollback()
                await session.execute(
                    update(AnalysisSchedule)
                    .where(AnalysisSchedule.id == schedule_id)
                    .values(next_run_at=compute_next_run(max(now, slot), interval))
                )
                await session.commit()
                continue

            schedule.last_run_at = now
            schedule.next_run_at = compute_next_run(max(now, slot), interval)
            await session.commit()
            claimed.append(run.id)

    return claimed


async def create_manual_run(
    session: AsyncSession, schedule: AnalysisSchedule, *, now: datetime | None = None
) -> ScheduleRun | None:
    """"立即执行"：用当前秒作为 slot，唯一约束保证同一秒不会重复触发。"""
    now = (now or datetime.utcnow()).replace(microsecond=0)
    run = ScheduleRun(schedule_id=schedule.id, scheduled_for=now, status="queued")
    session.add(run)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None
    return run


class Scheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        poll_seconds: float | None = None,
        submit=None,
    ) -> None:
        settings = get_settings()
        if session_factory is None:
            from app.database import async_session as default_factory

            session_factory = default_factory
        self._session_factory = session_factory
        self._poll = poll_seconds if poll_seconds is not None else settings.scheduler_poll_seconds
        self._submit = submit  # 可注入：默认 task_queue.submit
        self._task: asyncio.Task | None = None
        self._running = False

    async def _default_submit(self, run_id: str) -> str:
        from app.services.task_queue import task_queue

        return await task_queue.submit("scheduled_analysis", {"run_id": run_id})

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="scheduler")
        logger.info("调度器已启动 poll=%ss", self._poll)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 - 调度循环不能因为一次异常退出
                logger.exception("调度 tick 异常")
            await asyncio.sleep(self._poll)

    async def tick(self, now: datetime | None = None) -> list[str]:
        """跑一轮：抢占到期计划并提交任务。返回本轮的 run id。"""
        run_ids = await claim_due_schedules(self._session_factory, now=now)
        submit = self._submit or self._default_submit
        submitted: list[str] = []
        for run_id in run_ids:
            try:
                task_id = await submit(run_id)
            except Exception as error:  # noqa: BLE001 - 单条失败不影响其它计划
                logger.warning("提交定时任务失败 run=%s: %s", run_id, error)
                await self._mark_failed(run_id, f"提交失败：{error}")
                continue
            await self._attach_task(run_id, task_id)
            submitted.append(run_id)
        return submitted

    async def _attach_task(self, run_id: str, task_id: str) -> None:
        async with self._session_factory() as session:
            run = await session.get(ScheduleRun, run_id)
            if run is not None:
                run.task_id = task_id
                await session.commit()

    async def _mark_failed(self, run_id: str, reason: str) -> None:
        async with self._session_factory() as session:
            run = await session.get(ScheduleRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error = reason[:500]
            run.finished_at = datetime.utcnow()
            schedule = await session.get(AnalysisSchedule, run.schedule_id)
            if schedule is not None:
                schedule.consecutive_failures += 1
                schedule.last_status = "failed"
                schedule.last_error = reason[:500]
                if schedule.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    schedule.enabled = False
            await session.commit()


def schedule_to_dict(schedule: AnalysisSchedule) -> dict:
    return {
        "id": schedule.id,
        "name": schedule.name,
        "question": schedule.question,
        "datasource_ids": json.loads(schedule.datasource_ids or "[]"),
        "interval_minutes": schedule.interval_minutes,
        "enabled": bool(schedule.enabled),
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "last_status": schedule.last_status,
        "last_error": schedule.last_error,
        "consecutive_failures": schedule.consecutive_failures,
        "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
    }


scheduler = Scheduler()
