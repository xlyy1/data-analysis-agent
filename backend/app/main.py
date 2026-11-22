"""FastAPI 入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.api import conversation, datasource, report, tasks
from app.services import task_handlers  # noqa: F401  注册任务处理器
from app.services.task_queue import task_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    await init_db()
    # 启动后台任务 worker，并恢复上次没跑完的任务
    await task_queue.start()
    try:
        yield
    finally:
        await task_queue.stop()


app = FastAPI(
    title="对话式数据分析师 Agent",
    description="面向中小工厂和电商商家的 AI 数据分析助手",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(conversation.router)
app.include_router(datasource.router)
app.include_router(report.router)
app.include_router(tasks.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
