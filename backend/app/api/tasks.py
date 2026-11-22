"""后台任务接口：提交、查状态、列列表。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.task_queue import handler_for, task_queue

router = APIRouter(prefix="/api/tasks", tags=["任务"])


class SubmitTaskRequest(BaseModel):
    kind: str = Field(..., description="任务类型，需已在服务端注册处理器")
    payload: dict = Field(default_factory=dict)


class SubmitTaskResponse(BaseModel):
    id: str
    status: str


@router.post("", response_model=SubmitTaskResponse)
async def submit_task(req: SubmitTaskRequest):
    """提交长任务，立即返回任务 id；执行进度用 GET /api/tasks/{id} 查。"""
    if handler_for(req.kind) is None:
        raise HTTPException(400, f"未注册的任务类型：{req.kind}")
    task_id = await task_queue.submit(req.kind, req.payload)
    return SubmitTaskResponse(id=task_id, status="queued")


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = await task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("")
async def list_tasks(status: str | None = None, limit: int = 20):
    return {"items": await task_queue.list(status=status, limit=limit)}
