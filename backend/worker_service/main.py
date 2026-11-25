"""任务服务（独立进程）：任务提交、查询、执行、定时调度、健康检查。

为什么拆出来：任务队列和 API 共享同一个进程时，一个长任务的重试会跟接口抢
事件循环，扩容也只能整机扩。拆成独立服务后，API 只做转发，任务服务可以单独
扩 worker 数、单独重启，接口侧用超时 + 重试 + 熔断兜住下游抖动。

调度器也放在这里：它需要把任务投进本地队列（不走 HTTP），并且和 worker 一起
扩容时靠数据库唯一约束保证不重复执行。

启动：uvicorn worker_service.main:app --port 8001
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.errors import AppError, install_error_handlers
from app.database import ensure_schema, init_db
from app.observability.logging import RequestContextMiddleware, setup_logging
from app.observability.metrics import render_metrics
from app.services import task_handlers  # noqa: F401  注册处理器
from app.services.scheduler import scheduler
from app.services.task_queue import handler_for, task_queue

logger = logging.getLogger(__name__)


class SubmitTaskRequest(BaseModel):
    kind: str = Field(..., description="任务类型，需已在服务端注册处理器")
    payload: dict = Field(default_factory=dict)


class SubmitTaskResponse(BaseModel):
    id: str
    status: str


def _bootstrap_database() -> None:
    ensure_schema()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    if settings.is_test:
        await init_db()
    else:
        await asyncio.to_thread(_bootstrap_database)
    await task_queue.start()
    if settings.scheduler_enabled:
        await scheduler.start()
    try:
        yield
    finally:
        if settings.scheduler_enabled:
            await scheduler.stop()
        await task_queue.stop()


app = FastAPI(title="任务服务", version="1.0.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
install_error_handlers(app)


@app.get("/healthz")
async def healthz():
    """给上游做健康检查用：进程活着就算健康。"""
    return {"status": "ok", "service": "task-worker"}


@app.get("/readyz")
async def readyz():
    """队列已启动且至少注册了一个处理器才算就绪。"""
    ready = handler_for("echo") is not None and handler_for("scheduled_analysis") is not None
    body = {
        "status": "ok" if ready else "degraded",
        "service": "task-worker",
        "handlers_ready": ready,
    }
    if not ready:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=body)
    return body


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    if not get_settings().metrics_enabled:
        return PlainTextResponse("# metrics disabled\n")
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")


@app.post("/tasks", response_model=SubmitTaskResponse)
async def submit_task(req: SubmitTaskRequest):
    if handler_for(req.kind) is None:
        raise AppError("task_kind_unknown", f"未注册的任务类型：{req.kind}", status_code=400)
    task_id = await task_queue.submit(req.kind, req.payload)
    return SubmitTaskResponse(id=task_id, status="queued")


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = await task_queue.get(task_id)
    if not task:
        raise AppError("task_not_found", "任务不存在", status_code=404)
    return task


@app.get("/tasks")
async def list_tasks(status: str | None = None, limit: int = 20):
    return {"items": await task_queue.list(status=status, limit=limit)}


@app.post("/scheduler/tick")
async def scheduler_tick():
    """手工触发一轮调度（运维 / 测试用，不需要等 poll 间隔）。"""
    run_ids = await scheduler.tick()
    return {"claimed": len(run_ids), "runs": run_ids}
