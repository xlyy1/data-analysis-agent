"""定时调度测试：抢占幂等、失败隔离、连续失败自动停用、任务处理器幂等。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.schedule import AnalysisSchedule, ScheduleRun
from app.services.scheduler import (
    MAX_CONSECUTIVE_FAILURES,
    Scheduler,
    claim_due_schedules,
    compute_next_run,
    create_manual_run,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sched.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def add_schedule(factory, *, due: bool = True, interval: int = 60, name: str = "日报") -> str:
    now = datetime.utcnow()
    async with factory() as session:
        schedule = AnalysisSchedule(
            user_id="u1",
            name=name,
            question="各城市销售额",
            datasource_ids=json.dumps([]),
            interval_minutes=interval,
            enabled=True,
            next_run_at=now - timedelta(minutes=5) if due else now + timedelta(minutes=5),
        )
        session.add(schedule)
        await session.commit()
        return schedule.id


class TestClaim:
    async def test_due_schedule_claimed_once_and_rescheduled(self, factory):
        schedule_id = await add_schedule(factory)
        claimed = await claim_due_schedules(factory, now=datetime.utcnow())
        assert len(claimed) == 1

        async with factory() as session:
            schedule = await session.get(AnalysisSchedule, schedule_id)
            assert schedule.next_run_at > datetime.utcnow()
            assert schedule.last_run_at is not None
            runs = (await session.execute(select(ScheduleRun))).scalars().all()
            assert len(runs) == 1
            assert runs[0].status == "queued"
            assert runs[0].schedule_id == schedule_id

    async def test_not_due_schedule_ignored(self, factory):
        await add_schedule(factory, due=False)
        assert await claim_due_schedules(factory, now=datetime.utcnow()) == []

    async def test_disabled_schedule_ignored(self, factory):
        schedule_id = await add_schedule(factory)
        async with factory() as session:
            schedule = await session.get(AnalysisSchedule, schedule_id)
            schedule.enabled = False
            await session.commit()
        assert await claim_due_schedules(factory, now=datetime.utcnow()) == []

    async def test_same_slot_is_idempotent(self, factory):
        """模拟"另一个副本已经抢到同一个时刻"：唯一键挡住，且不会卡死循环。"""
        schedule_id = await add_schedule(factory)
        async with factory() as session:
            schedule = await session.get(AnalysisSchedule, schedule_id)
            slot = schedule.next_run_at
            session.add(ScheduleRun(schedule_id=schedule_id, scheduled_for=slot, status="queued"))
            await session.commit()

        claimed = await claim_due_schedules(factory, now=datetime.utcnow())
        assert claimed == [], "同一时刻不应重复抢占"

        async with factory() as session:
            schedule = await session.get(AnalysisSchedule, schedule_id)
            assert schedule.next_run_at > slot, "撞唯一键后必须把 next_run_at 往前推，否则每轮都撞"
            assert len((await session.execute(select(ScheduleRun))).scalars().all()) == 1

    async def test_compute_next_run_monotonic(self):
        now = datetime.utcnow()
        assert compute_next_run(now, 60) == now + timedelta(minutes=60)
        assert compute_next_run(now, 0) == now + timedelta(minutes=1)


class TestManualRun:
    async def test_same_second_manual_run_is_rejected(self, factory):
        schedule_id = await add_schedule(factory, due=False)
        async with factory() as session:
            schedule = await session.get(AnalysisSchedule, schedule_id)
            fixed = datetime(2026, 5, 1, 12, 0, 0)
            first = await create_manual_run(session, schedule, now=fixed)
            assert first is not None
            second = await create_manual_run(session, schedule, now=fixed)
            assert second is None, "同一秒重复点击不应产生第二条 run"


class TestTick:
    async def test_tick_submits_and_records_task_id(self, factory):
        await add_schedule(factory)
        submitted: list[str] = []

        async def submit(run_id: str) -> str:
            submitted.append(run_id)
            return "task-1"

        scheduler = Scheduler(factory, poll_seconds=0.01, submit=submit)
        run_ids = await scheduler.tick(now=datetime.utcnow())
        assert len(run_ids) == 1
        assert submitted == run_ids

        async with factory() as session:
            run = await session.get(ScheduleRun, run_ids[0])
            assert run.task_id == "task-1"

    async def test_failure_is_isolated_between_schedules(self, factory):
        good_id = await add_schedule(factory, name="正常计划")
        bad_id = await add_schedule(factory, name="坏计划")

        async def submit(run_id: str) -> str:
            async with factory() as session:
                run = await session.get(ScheduleRun, run_id)
                if run.schedule_id == bad_id:
                    raise RuntimeError("任务服务挂了")
            return "task-ok"

        scheduler = Scheduler(factory, poll_seconds=0.01, submit=submit)
        run_ids = await scheduler.tick(now=datetime.utcnow())
        assert len(run_ids) == 1, "只有成功的那个被记为已提交"

        async with factory() as session:
            runs = (await session.execute(select(ScheduleRun))).scalars().all()
            by_schedule = {run.schedule_id: run for run in runs}
            assert by_schedule[good_id].status == "queued"
            assert by_schedule[bad_id].status == "failed"
            assert "任务服务挂了" in by_schedule[bad_id].error

            bad = await session.get(AnalysisSchedule, bad_id)
            good = await session.get(AnalysisSchedule, good_id)
            assert bad.consecutive_failures == 1
            assert good.consecutive_failures == 0

    async def test_schedule_disabled_after_repeated_failures(self, factory):
        schedule_id = await add_schedule(factory)
        scheduler = Scheduler(factory, poll_seconds=0.01, submit=None)
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            async with factory() as session:
                run = ScheduleRun(
                    schedule_id=schedule_id, scheduled_for=datetime.utcnow(), status="queued"
                )
                session.add(run)
                await session.commit()
                run_id = run.id
            await scheduler._mark_failed(run_id, "boom")

        async with factory() as session:
            schedule = await session.get(AnalysisSchedule, schedule_id)
            assert schedule.consecutive_failures == MAX_CONSECUTIVE_FAILURES
            assert schedule.enabled is False, "连续失败达到上限应自动停用，避免持续告警"
            assert schedule.last_status == "failed"


class TestScheduledAnalysisHandler:
    async def test_handler_skips_already_succeeded_run(self, factory, monkeypatch):
        import app.database as database_module
        from app.services import task_handlers

        schedule_id = await add_schedule(factory)
        async with factory() as session:
            run = ScheduleRun(
                schedule_id=schedule_id, scheduled_for=datetime.utcnow(), status="succeeded"
            )
            session.add(run)
            await session.commit()
            run_id = run.id

        # 让处理器连到测试库
        monkeypatch.setattr(database_module, "async_session", factory)

        async def boom(*args, **kwargs):
            raise AssertionError("已成功的 run 不应再次执行")

        monkeypatch.setattr("app.services.conversation.ConversationService.run_agent", boom)
        result = await task_handlers.scheduled_analysis({"run_id": run_id})
        assert result["skipped"] is True
        assert result["reason"] == "already_succeeded"

    async def test_handler_marks_failure_and_reraises(self, factory, monkeypatch):
        import app.database as database_module
        from app.services import task_handlers

        schedule_id = await add_schedule(factory)
        async with factory() as session:
            run = ScheduleRun(
                schedule_id=schedule_id, scheduled_for=datetime.utcnow(), status="queued"
            )
            session.add(run)
            await session.commit()
            run_id = run.id

        monkeypatch.setattr(database_module, "async_session", factory)

        async def failing_run_agent(self, *args, **kwargs):
            raise RuntimeError("模型超时")

        monkeypatch.setattr(
            "app.services.conversation.ConversationService.run_agent", failing_run_agent
        )

        with pytest.raises(RuntimeError):
            await task_handlers.scheduled_analysis({"run_id": run_id})

        async with factory() as session:
            run = await session.get(ScheduleRun, run_id)
            assert run.status == "failed"
            assert "模型超时" in run.error
            assert run.attempts == 1
            schedule = await session.get(AnalysisSchedule, schedule_id)
            assert schedule.consecutive_failures == 1
            assert schedule.last_status == "failed"
            assert schedule.last_run_at == run.scheduled_for, "失败也要回填上次运行时间"

    async def test_handler_rejects_missing_run_id(self):
        from app.services import task_handlers

        with pytest.raises(ValueError):
            await task_handlers.scheduled_analysis({})
