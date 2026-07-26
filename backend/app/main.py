"""FastAPI 入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.api import conversation, datasource, report


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
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


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
