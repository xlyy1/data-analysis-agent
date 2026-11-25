"""定时分析 API：CRUD + 立即执行 + 运行历史。"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete as sqldelete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.core.errors import AppError
from app.database import get_db
from app.models.schedule import AnalysisSchedule, ScheduleRun
from app.models.user import ROLE_ADMIN, User
from app.services.audit import record_audit
from app.services.scheduler import (
    compute_next_run,
    create_manual_run,
    schedule_to_dict,
)
from app.services.task_service_client import DownstreamError, TaskServiceClient

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

MIN_INTERVAL_MINUTES = 5


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=2, max_length=2000)
    datasource_ids: list[str] = Field(default_factory=list)
    interval_minutes: int = Field(default=1440, ge=MIN_INTERVAL_MINUTES, le=60 * 24 * 31)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    question: str | None = Field(default=None, min_length=2, max_length=2000)
    datasource_ids: list[str] | None = None
    interval_minutes: int | None = Field(default=None, ge=MIN_INTERVAL_MINUTES, le=60 * 24 * 31)
    enabled: bool | None = None


async def _owned(schedule_id: str, user: User, db: AsyncSession) -> AnalysisSchedule:
    schedule = (
        await db.execute(select(AnalysisSchedule).where(AnalysisSchedule.id == schedule_id))
    ).scalar_one_or_none()
    if schedule is None or (user.role != ROLE_ADMIN and schedule.user_id != user.id):
        raise AppError("schedule_not_found", "定时任务不存在", status_code=404)
    return schedule


def _client() -> TaskServiceClient:
    from app.config import get_settings

    settings = get_settings()
    return TaskServiceClient(
        settings.task_service_url,
        timeout=settings.task_service_timeout_seconds,
        retries=settings.task_service_retries,
    )


@router.get("")
async def list_schedules(
    user: User = Depends(require("schedule:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AnalysisSchedule).order_by(AnalysisSchedule.created_at.desc())
    if user.role != ROLE_ADMIN:
        stmt = stmt.where(AnalysisSchedule.user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [schedule_to_dict(row) for row in rows]}


@router.post("", status_code=201)
async def create_schedule(
    payload: ScheduleCreate,
    user: User = Depends(require("schedule:write")),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.utcnow()
    schedule = AnalysisSchedule(
        user_id=user.id,
        name=payload.name,
        question=payload.question,
        datasource_ids=json.dumps(payload.datasource_ids),
        interval_minutes=payload.interval_minutes,
        enabled=payload.enabled,
        next_run_at=compute_next_run(now, payload.interval_minutes),
    )
    db.add(schedule)
    await db.commit()
    await record_audit(
        db, user_id=user.id, action="schedule_create", detail={"id": schedule.id, "name": schedule.name}
    )
    return schedule_to_dict(schedule)


@router.get("/{schedule_id}")
async def get_schedule(
    schedule_id: str,
    user: User = Depends(require("schedule:read")),
    db: AsyncSession = Depends(get_db),
):
    return schedule_to_dict(await _owned(schedule_id, user, db))


@router.patch("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdate,
    user: User = Depends(require("schedule:write")),
    db: AsyncSession = Depends(get_db),
):
    schedule = await _owned(schedule_id, user, db)
    if payload.name is not None:
        schedule.name = payload.name
    if payload.question is not None:
        schedule.question = payload.question
    if payload.datasource_ids is not None:
        schedule.datasource_ids = json.dumps(payload.datasource_ids)
    if payload.interval_minutes is not None:
        schedule.interval_minutes = payload.interval_minutes
        schedule.next_run_at = compute_next_run(datetime.utcnow(), payload.interval_minutes)
    if payload.enabled is not None:
        schedule.enabled = payload.enabled
        if payload.enabled and schedule.next_run_at is None:
            schedule.next_run_at = compute_next_run(datetime.utcnow(), schedule.interval_minutes)
    await db.commit()
    await record_audit(db, user_id=user.id, action="schedule_update", detail={"id": schedule.id})
    return schedule_to_dict(schedule)


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    user: User = Depends(require("schedule:write")),
    db: AsyncSession = Depends(get_db),
):
    schedule = await _owned(schedule_id, user, db)
    # 先删运行记录再删计划：schedule_runs.schedule_id 有外键，
    # 且 SQLite 连接上开了 PRAGMA foreign_keys=ON，直接删父行会 IntegrityError。
    await db.execute(sqldelete(ScheduleRun).where(ScheduleRun.schedule_id == schedule_id))
    await db.delete(schedule)
    await db.commit()
    await record_audit(db, user_id=user.id, action="schedule_delete", detail={"id": schedule_id})
    return {"status": "deleted"}


@router.post("/{schedule_id}/run")
async def run_now(
    schedule_id: str,
    user: User = Depends(require("schedule:write")),
    db: AsyncSession = Depends(get_db),
):
    """立即执行一次：建 run（唯一约束防重复）→ 提交任务服务。"""
    schedule = await _owned(schedule_id, user, db)
    run = await create_manual_run(db, schedule)
    if run is None:
        raise AppError("duplicate_run", "同一秒内已经触发过，请稍后再试", status_code=409)

    try:
        created = await _client().submit("scheduled_analysis", {"run_id": run.id})
    except DownstreamError as error:
        run.status = "failed"
        run.error = f"任务服务不可用：{error}"[:500]
        await db.commit()
        raise AppError(
            "task_service_unavailable",
            "任务服务不可用，已记录本次失败",
            status_code=502,
            details={"reason": str(error)[:200]},
        ) from error

    run.task_id = created["id"]
    await db.commit()
    await record_audit(db, user_id=user.id, action="schedule_run_now", detail={"id": schedule.id})
    return {"run_id": run.id, "task_id": created["id"], "status": run.status}


@router.get("/{schedule_id}/runs")
async def list_runs(
    schedule_id: str,
    user: User = Depends(require("schedule:read")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
):
    await _owned(schedule_id, user, db)
    rows = (
        await db.execute(
            select(ScheduleRun)
            .where(ScheduleRun.schedule_id == schedule_id)
            .order_by(ScheduleRun.scheduled_for.desc())
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": run.id,
                "scheduled_for": run.scheduled_for.isoformat(),
                "status": run.status,
                "attempts": run.attempts,
                "task_id": run.task_id,
                "error": run.error,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
            for run in rows
        ]
    }
