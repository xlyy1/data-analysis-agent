"""注册到任务队列的处理器。

- trace_cleanup       清理过期执行追踪（trace_events 只保留最近 N 天）
- scheduled_analysis  定时分析：跑一次 Agent → 存会话 → 生成报告（幂等）
- echo                联调用
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from app.observability import trace
from app.observability.metrics import schedule_runs_total
from app.services.task_queue import register_handler
from app.core.sqlite import sqlite_connection

logger = logging.getLogger(__name__)


@register_handler("trace_cleanup")
async def trace_cleanup(payload: dict) -> dict:
    """删除 N 天前的 trace 事件，返回删了多少条。"""
    days = int(payload.get("days", 30))
    cutoff = time.time() - days * 86400
    path = trace.get_db_path()
    with sqlite_connection(path) as conn:
        cursor = conn.execute("DELETE FROM trace_events WHERE started_at < ?", (cutoff,))
        deleted = cursor.rowcount or 0
        conn.commit()
    return {"deleted": deleted, "days": days}


@register_handler("echo")
async def echo(payload: dict) -> dict:
    return {"echo": payload, "at": time.time()}


@register_handler("scheduled_analysis")
async def scheduled_analysis(payload: dict) -> dict:
    """执行一次定时分析。

    幂等：run 已经是 succeeded 就直接返回（任务队列重投 / 重启恢复都会走到这里）。
    失败：把 run 标记 failed、计划累计失败次数，连续 3 次自动停用，
    异常继续抛出，交给任务队列按 task_max_retries 重试。
    """
    from app.database import async_session
    from app.models.report import Report
    from app.models.schedule import AnalysisSchedule, ScheduleRun
    from app.services.conversation import ConversationService, build_assistant_metadata
    from app.services.datasource_context import resolve_datasource_context
    from app.services.report import ReportService
    from app.services.scheduler import MAX_CONSECUTIVE_FAILURES

    run_id = payload.get("run_id")
    if not run_id:
        raise ValueError("scheduled_analysis 缺少 run_id")

    async with async_session() as session:
        run = await session.get(ScheduleRun, run_id)
        if run is None:
            return {"skipped": True, "reason": "run_not_found"}
        if run.status == "succeeded":
            return {"skipped": True, "reason": "already_succeeded", "run_id": run_id}

        run.status = "running"
        run.attempts += 1
        await session.commit()

        schedule = await session.get(AnalysisSchedule, run.schedule_id)
        if schedule is None:
            run.status = "failed"
            run.error = "计划已被删除"
            run.finished_at = datetime.utcnow()
            await session.commit()
            schedule_runs_total.inc(status="failed")
            return {"skipped": True, "reason": "schedule_deleted"}

        try:
            datasource_ids = json.loads(schedule.datasource_ids or "[]")
            resolved_ids, schemas, configs = await resolve_datasource_context(
                session, datasource_ids
            )
            svc = ConversationService(session)
            title = f"[定时] {schedule.name} {run.scheduled_for:%m-%d %H:%M}"
            conversation = await svc.create_conversation(schedule.user_id, title=title)
            await svc.add_message(conversation.id, "user", schedule.question)

            state = await svc.run_agent(
                conversation.id,
                schedule.question,
                resolved_ids,
                schemas,
                configs,
                allow_write=False,
                user_id=schedule.user_id,
            )
            answer = state.get("final_response") or "本次定时分析未产出结论。"
            metadata = build_assistant_metadata(state)
            await svc.add_message(conversation.id, "assistant", answer, metadata)

            markdown = ReportService.generate_markdown(
                schedule.question,
                answer,
                metadata.get("diagnosis_causes", []),
                metadata.get("diagnosis_suggestions", []),
                metadata.get("sql", ""),
                metadata.get("data_columns", []),
                metadata.get("data_rows", []),
            )
            report = Report(
                user_id=schedule.user_id,
                conversation_id=conversation.id,
                title=f"{schedule.name} · {run.scheduled_for:%Y-%m-%d %H:%M}",
                question=schedule.question,
                sql=metadata.get("sql", ""),
                markdown=markdown,
            )
            session.add(report)
            await session.commit()

            run.status = "succeeded"
            run.error = None
            run.finished_at = datetime.utcnow()
            schedule.last_status = "succeeded"
            schedule.last_run_at = run.scheduled_for
            schedule.last_error = None
            schedule.consecutive_failures = 0
            await session.commit()
            schedule_runs_total.inc(status="succeeded")
            return {
                "run_id": run_id,
                "conversation_id": conversation.id,
                "report_id": report.id,
            }

        except Exception as error:  # noqa: BLE001 - 失败要落库后再抛出以便重试
            logger.warning("定时分析失败 run=%s: %s", run_id, error, exc_info=True)
            run.status = "failed"
            run.error = f"{type(error).__name__}: {error}"[:500]
            run.finished_at = datetime.utcnow()
            schedule.consecutive_failures += 1
            schedule.last_status = "failed"
            schedule.last_run_at = run.scheduled_for
            schedule.last_error = run.error
            if schedule.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                schedule.enabled = False
                logger.warning(
                    "计划连续失败 %d 次，已自动停用 schedule=%s",
                    schedule.consecutive_failures,
                    schedule.id,
                )
            await session.commit()
            schedule_runs_total.inc(status="failed")
            raise
