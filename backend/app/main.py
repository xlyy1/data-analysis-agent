"""FastAPI 入口。

启动顺序（每一步失败都有明确后果，不允许静默跳过）：
1. 结构化日志（JSON + request_id）
2. 数据库迁移（Alembic upgrade head）→ 空库/旧库都能直接拉起
3. 初始管理员（用户表为空时）
4. 样例数据源（数据源表为空时，可在 .env 关掉）
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, conversation, datasource, report, schedules, sql_debug, system, tasks
from app.config import get_settings
from app.core.errors import install_error_handlers
from app.database import async_session, ensure_schema, init_db
from app.observability.logging import RequestContextMiddleware, setup_logging
from app.observability.metrics import MetricsMiddleware
from app.services.bootstrap import ensure_bootstrap_admin
from app.services.seed import ensure_sample_datasource

logger = logging.getLogger(__name__)

APP_VERSION = "1.0.0"

DESCRIPTION = """
面向中小工厂 / 电商商家的**自然语言数据分析 Agent**。

- 自然语言 → SQL（只读执行，自动补 LIMIT，超时/行数/字符数全有上限）
- 输出 = SQL + 结果表 + 图表配置 + 中文结论；模糊问题会主动反问澄清
- 角色：`admin` / `analyst` / `viewer`；viewer 不能改数据源、不能执行写 SQL
- 所有错误统一返回 `{"error": {code, message, details, request_id}}`
"""


def _bootstrap_database() -> None:
    settings = get_settings()
    if settings.is_test:
        return
    ensure_schema()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    logger.info("启动 data-agent-api env=%s", settings.app_env)

    if settings.is_test:
        await init_db()
    else:
        await asyncio.to_thread(_bootstrap_database)
    async with async_session() as session:
        await ensure_bootstrap_admin(session)
        try:
            # 样例数据只是演示便利，任何问题都不能阻止服务启动
            await ensure_sample_datasource(session)
        except Exception:  # noqa: BLE001
            logger.warning("样例数据播种失败，跳过（不影响启动）", exc_info=True)

    yield
    logger.info("data-agent-api 已停止")


app = FastAPI(
    title="对话式数据分析师 Agent",
    description=DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan,
    contact={"name": "data-agent", "url": "https://github.com/"},
)

settings = get_settings()
allow_all = settings.cors_origin_list == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=not allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestContextMiddleware)

install_error_handlers(app)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(conversation.router)
app.include_router(datasource.router)
app.include_router(report.router)
app.include_router(schedules.router)
app.include_router(sql_debug.router)
app.include_router(tasks.router)


@app.get("/api/health", tags=["system"], include_in_schema=False)
async def health():
    """兼容旧前端的健康检查。"""
    return {"status": "ok", "version": APP_VERSION}


@app.get("/", tags=["system"], include_in_schema=False)
async def index():
    return {
        "service": "data-agent-api",
        "version": APP_VERSION,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/healthz",
        "ready": "/readyz",
        "metrics": "/metrics",
    }
