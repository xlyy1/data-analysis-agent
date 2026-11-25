"""统一错误体。

对外只暴露 `{"error": {code, message, details, request_id}}`：
- code 是稳定的机器可读标识（前端按它分支，不解析文案）；
- message 是给用户看的中文；
- details 只在确实有助于排查时给，绝不含 SQL 全文 / 连接串 / 堆栈。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """业务异常：显式带状态码和错误码。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_payload(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        },
        # 兼容 FastAPI 默认的 detail 字段（老客户端 / 老测试仍在读它）。
        # 新代码请统一读 error.code / error.message；detail 会在下个大版本移除。
        "detail": message,
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("x-request-id", "")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                exc.code, exc.message, details=exc.details, request_id=_request_id(request)
            ),
        )

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = "http_error" if exc.status_code >= 500 else "request_error"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                code,
                str(exc.detail),
                request_id=_request_id(request),
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "validation_error",
                "请求参数不合法",
                details={"errors": [
                    {"loc": list(err.get("loc", [])), "msg": err.get("msg", "")}
                    for err in exc.errors()
                ]},
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_payload(
                "internal_error",
                "服务内部错误，请稍后重试",
                request_id=_request_id(request),
            ),
        )
