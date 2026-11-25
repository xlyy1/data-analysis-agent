"""系统探针与指标：/healthz、/readyz、/metrics。

- /healthz 只看进程活着（给容器 liveness 用，挂了就重启）；
- /readyz 看依赖（元数据库 + 关键表 + 任务服务可达性），不通就不接流量；
- /metrics Prometheus 文本格式。
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.database import database_ready
from app.observability.metrics import build_info, render_metrics, task_queue_depth
from app.observability.trace import get_db_path as trace_db_path

router = APIRouter(tags=["system"])

APP_VERSION = "1.0.0"
_STARTED_AT = time.time()


@router.get("/healthz")
async def healthz():
    """liveness：只要进程能响应就算活着，不查依赖。"""
    return {
        "status": "ok",
        "service": "data-agent-api",
        "version": APP_VERSION,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


@router.get("/readyz")
async def readyz():
    """readiness：依赖不可用就返回 503，让编排层不要把流量打进来。"""
    checks: dict[str, dict] = {}
    ok = True

    db_ok, db_detail = database_ready()
    checks["database"] = {"ok": db_ok, "detail": db_detail}
    ok = ok and db_ok

    trace_path = trace_db_path()
    trace_ok = trace_path.exists() or trace_path.parent.exists()
    checks["trace_store"] = {
        "ok": trace_ok,
        "detail": str(trace_path) if trace_ok else f"unwritable: {trace_path.parent}",
    }

    settings = get_settings()
    task_detail = "not configured"
    task_ok = True
    try:
        async with httpx.AsyncClient(timeout=min(settings.task_service_timeout_seconds, 2.0)) as client:
            response = await client.get(f"{settings.task_service_url.rstrip('/')}/healthz")
            task_ok = response.status_code == 200
            task_detail = f"http {response.status_code}"
    except Exception as error:  # noqa: BLE001 - 探针不抛异常
        task_ok = False
        task_detail = f"unreachable: {type(error).__name__}"
    checks["task_service"] = {"ok": task_ok, "detail": task_detail}
    # 任务服务不可用不阻断读路径（问答不依赖它），只在就绪响应里标出来
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(
                f"{settings.task_service_url.rstrip('/')}/tasks", params={"limit": 1}
            )
            if response.status_code == 200:
                payload = response.json()
                items = payload.get("items") or []
                queued = sum(1 for item in items if item.get("status") in ("queued", "running"))
                task_queue_depth.set(queued)
    except Exception:  # noqa: BLE001
        pass

    build_info.set(1, version=APP_VERSION)
    body = {
        "status": "ok" if ok else "degraded",
        "checks": checks,
        "version": APP_VERSION,
    }
    if not ok:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=body)
    return body


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    if not get_settings().metrics_enabled:
        return PlainTextResponse("# metrics disabled\n")
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")
