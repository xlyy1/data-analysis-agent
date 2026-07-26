"""SQLite 数据库引擎与会话管理"""

from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# Use absolute path for database, resolving from backend directory
DB_FILE = str(Path(__file__).resolve().parent.parent.parent / "data" / "agent.db").replace("\\", "/")

engine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_FILE}",
    echo=False,
    future=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖：返回异步数据库会话"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """创建所有表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
