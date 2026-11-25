"""结构化日志 + 请求上下文（request_id）。

每条日志都带 request_id，配合响应头 `X-Request-ID` 可以把"用户看到的一次报错"
和"服务端那一串日志"对上。审计事件另走 operation_logs 表。
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")

# 这些路径不记访问日志，避免健康检查刷屏
QUIET_PATHS = {"/healthz", "/readyz", "/metrics"}

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
            + f".{int(record.msecs):03d}",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        user_id = user_id_var.get()
        if user_id:
            payload["user_id"] = user_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        prefix = f"[{rid[:8]}] " if rid else ""
        return f"{time.strftime('%H:%M:%S')} {record.levelname:<7} {prefix}{record.getMessage()}"


def setup_logging(level: str = "INFO", json_enabled: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_enabled else PlainFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # uvicorn 的 access log 和我们的访问日志重复，关掉它自己的
    logging.getLogger("uvicorn.access").disabled = True


def new_request_id() -> str:
    return uuid.uuid4().hex


def _incoming_request_id(request: Request) -> str:
    """只接受合理长度的十六进制/安全字符，避免 header 注入进日志。"""
    raw = request.headers.get("x-request-id", "")
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")[:64]
    return cleaned or new_request_id()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """注入 request_id、记录访问日志、统一响应头。"""

    async def dispatch(self, request: Request, call_next):
        request_id = _incoming_request_id(request)
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            if request.url.path not in QUIET_PATHS:
                logging.getLogger("access").info(
                    "%s %s -> %s",
                    request.method,
                    request.url.path,
                    status_code,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "duration_ms": round(duration_ms, 2),
                        "client": request.client.host if request.client else "",
                    },
                )
            request_id_var.reset(token)
