"""FastAPI 入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.api import conversation, datasource, report, tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库；任务执行已拆到独立服务（worker_service），API 不再消费队列
    await init_db()
    yield


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
