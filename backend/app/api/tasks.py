"""后台任务接口：API 侧只做转发，执行全在 task-worker。

- 下游超时/5xx 有限重试，仍失败返回 502，避免接口被拖住
- 熔断打开时快速失败，不再往下游打
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import require
from app.config import get_settings
from app.core.errors import AppError
from app.models.user import User
from app.services.task_service_client import (
    DownstreamError,
    DownstreamRejected,
    TaskServiceClient,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _client() -> TaskServiceClient:
    settings = get_settings()
    return TaskServiceClient(
        settings.task_service_url,
        timeout=settings.task_service_timeout_seconds,
        retries=settings.task_service_retries,
    )


class SubmitTaskRequest(BaseModel):
    kind: str = Field(..., description="任务类型，需已在任务服务注册处理器")
    payload: dict = Field(default_factory=dict)


class SubmitTaskResponse(BaseModel):
    id: str
    status: str


@router.post("", response_model=SubmitTaskResponse)
async def submit_task(
    req: SubmitTaskRequest,
    _: User = Depends(require("task:write")),
):
    """提交长任务：转发给任务服务，立即返回任务 id。"""
    try:
        created = await _client().submit(req.kind, req.payload)
    except DownstreamRejected as error:
        # 下游拒绝是请求问题（比如任务类型没注册），保留 4xx
        raise AppError("task_rejected", str(error), status_code=error.status_code) from error
    except DownstreamError as error:
        raise AppError(
            "task_service_unavailable", f"任务服务不可用：{error}", status_code=502
        ) from error
    return SubmitTaskResponse(id=created["id"], status=created.get("status", "queued"))


@router.get("/{task_id}")
async def get_task(task_id: str, _: User = Depends(require("task:read"))):
    try:
        task = await _client().get(task_id)
    except DownstreamError as error:
        raise AppError(
            "task_service_unavailable", f"任务服务不可用：{error}", status_code=502
        ) from error
    if task is None:
        raise AppError("task_not_found", "任务不存在", status_code=404)
    return task


@router.get("")
async def list_tasks(
    status: str | None = None,
    limit: int = 20,
    _: User = Depends(require("task:read")),
):
    try:
        items = await _client().list(status=status, limit=limit)
    except DownstreamError as error:
        raise AppError(
            "task_service_unavailable", f"任务服务不可用：{error}", status_code=502
        ) from error
    return {"items": items}


@router.get("/_health/downstream")
async def downstream_health(_: User = Depends(require("task:read"))):
    """探一下任务服务是否可达，排查 502 时用。"""
    client = _client()
    ok = await client.healthz()
    return {"task_service": "ok" if ok else "unreachable", "breaker": client.breaker_state}
