"""SQLite 元数据库引擎与会话管理。

- 路径来自 settings.database_url（留空则用 <repo>/data/agent.db），单测通过
  环境变量指向临时文件，测试之间互不污染。
- 表结构由 Alembic 管理（backend/alembic）；`init_db()` 只在测试 / 空库兜底时
  用 create_all 快速建表。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.paths import BACKEND_DIR, DATA_DIR
from app.core.sqlite import sqlite_connection

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


ASYNC_DRIVERS = {
    "sqlite": "sqlite+aiosqlite",
    "postgres": "postgresql+asyncpg",
    "postgresql": "postgresql+asyncpg",
    "mysql": "mysql+aiomysql",
}
SYNC_DRIVERS = ("+aiosqlite", "+asyncpg", "+aiomysql")


def resolve_database_url() -> str:
    """把配置/环境变量解析成**异步**引擎可用的 URL。

    实际部署时 .env 里常写成 `sqlite:///path`（Alembic/CLI 习惯），这里统一补齐
    异步驱动；相对路径一律按 backend/ 解析，避免不同启动目录算出不同文件。
    """
    raw = (get_settings().database_url or "").strip()
    if not raw:
        default_path = DATA_DIR / "agent.db"
        default_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{default_path.as_posix()}"

    prefix, sep, rest = raw.partition("://")
    if not sep:
        return raw
    scheme = prefix.split("+", 1)[0].lower()
    driver = ASYNC_DRIVERS.get(scheme, prefix)
    tail = rest.lstrip("/")
    if len(rest) - len(tail) >= 3:  # 四斜杠 = 绝对路径
        path = Path("/" + tail)
    elif scheme == "sqlite":
        path = Path(tail)
        if not path.is_absolute():
            path = (BACKEND_DIR / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        return f"{driver}://{rest}"
    return f"{driver}:///{path.as_posix()}"


def sync_database_url(url: str | None = None) -> str:
    """Alembic / sqlite3 用的同步 URL（去掉异步驱动后缀）。"""
    url = url or resolve_database_url()
    for driver in SYNC_DRIVERS:
        url = url.replace(driver, "")
    return url


DATABASE_URL = resolve_database_url()
_IS_SQLITE = DATABASE_URL.startswith("sqlite")
_IS_TEST = get_settings().is_test

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    # 测试里每个用例可能在不同事件循环里跑，连接池跨 loop 复用会炸；用 NullPool 隔离。
    poolclass=NullPool if _IS_TEST or _IS_SQLITE else None,
)


if _IS_SQLITE:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - 驱动回调
        """api 与 task-worker 是两个进程共享同一个 SQLite 文件。

        - WAL：读写不再互斥，避免 worker 写任务状态时把读接口卡住；
        - busy_timeout：遇到锁等待 5 秒再报错，而不是立刻 "database is locked"；
        - foreign_keys：SQLAlchemy 模型里有 FK 声明，SQLite 默认不校验。
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _load_models() -> None:
    """导入全部模型，保证 create_all / Alembic 能看到所有表。"""
    from app.models import (  # noqa: F401
        conversation,
        datasource,
        log,
        report,
        schedule,
        task,
        user,
    )


async def get_db() -> AsyncSession:
    """FastAPI 依赖：返回异步数据库会话"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """创建所有表（测试和兜底用；生产走 Alembic）。"""
    _load_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def run_migrations() -> None:
    """执行 `alembic upgrade head`。

    在启动期同步调用（SQLite 本地文件、毫秒级），保证空库能直接拉起、
    已有库能增量升级，避免"新加的表在旧库里不存在"这类事故。

    api 和 task-worker 两个进程会同时启动，可能同时执行迁移：
    先带退避重试，最后由 create_all 兜底（create_all 只建缺失的表，是幂等的）。
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_database_url())

    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            command.upgrade(config, "head")
            last_error = None
            break
        except Exception as error:  # noqa: BLE001 - 并发迁移 / 旧库脏状态
            last_error = error
            logger.warning("迁移第 %d 次失败：%s", attempt, error)
            time.sleep(1.0 * attempt)

    if last_error is not None:
        raise last_error
    logger.info("数据库迁移完成 url=%s", DATABASE_URL)


def ensure_schema() -> None:
    """迁移 + 兜底建表，保证服务一定能拿到可用的表结构。"""
    try:
        run_migrations()
    except Exception:  # noqa: BLE001 - 迁移失败不能直接让服务起不来
        logger.exception("Alembic 迁移失败，改用 create_all 兜底")
    from sqlalchemy import create_engine

    sync_engine = create_engine(sync_database_url())
    try:
        Base.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()



def database_ready() -> tuple[bool, str]:
    """readyz 用：能连上且关键表存在。"""

    url = resolve_database_url()
    if not url.startswith("sqlite"):
        return True, "non-sqlite datasource assumed ready"
    path = url.split("///", 1)[-1]
    if not Path(path).exists():
        return False, f"database file missing: {path}"
    try:
        with sqlite_connection(path) as conn:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
    except Exception as error:  # noqa: BLE001
        return False, f"database unreadable: {error}"
    required = {"users", "datasources", "conversations", "messages", "background_tasks"}
    missing = sorted(required - names)
    if missing:
        return False, f"missing tables: {','.join(missing)}"
    return True, "ok"
