"""任务服务（独立进程）：/tasks 的提交、查询、健康检查。

为什么拆出来：任务队列和 API 共享同一个进程时，一个长任务的重试会跟接口抢
事件循环，扩容也只能整机扩。拆成独立服务后，API 只做转发，任务服务可以单独
扩 worker 数、单独重启，接口侧用超时 + 重试 + 熔断兜住下游抖动。

启动：uvicorn worker_service.main:app --port 8001
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.database import init_db
from app.services import task_handlers  # noqa: F401  注册处理器
from app.services.task_queue import handler_for, task_queue

logger = logging.getLogger(__name__)


class SubmitTaskRequest(BaseModel):
    kind: str = Field(..., description="任务类型，需已在服务端注册处理器")
    payload: dict = Field(default_factory=dict)


class SubmitTaskResponse(BaseModel):
    id: str
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await task_queue.start()
    try:
        yield
    finally:
        await task_queue.stop()


app = FastAPI(title="任务服务", version="1.0.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    """给上游做健康检查用：进程活着且队列已启动才算健康。"""
    return {"status": "ok", "service": "task-worker"}


@app.post("/tasks", response_model=SubmitTaskResponse)
async def submit_task(req: SubmitTaskRequest):
    if handler_for(req.kind) is None:
        raise HTTPException(400, f"未注册的任务类型：{req.kind}")
    task_id = await task_queue.submit(req.kind, req.payload)
    return SubmitTaskResponse(id=task_id, status="queued")


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = await task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.get("/tasks")
async def list_tasks(status: str | None = None, limit: int = 20):
    return {"items": await task_queue.list(status=status, limit=limit)}
