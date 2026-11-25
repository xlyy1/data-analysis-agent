"""启动期演示数据播种。

只在"库里一个数据源都没有"时执行，所以重启不会重复插入。
Docker 镜像里也因此自带一份可问答的样例数据——面试官 clone 下来
`docker compose up` 就能直接演示，不用先准备业务文件。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.datasource import DataSource
from app.models.user import ROLE_ADMIN, User
from app.paths import SAMPLE_DIR, ensure_dir
from app.services.sample_data import build_all
from app.core.sqlite import sqlite_connection

logger = logging.getLogger(__name__)

SAMPLE_NAME = "示例·门店经营数据"


def _sample_db_usable(path: Path) -> bool:
    """样例库存在不代表可用：上一次生成可能被中断，留下有表没数据的空库。"""
    if not path.exists():
        return False
    import sqlite3

    try:
        with sqlite_connection(path) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            if len(tables) < 3:
                return False
            total = conn.execute('SELECT COUNT(*) FROM "订单明细"').fetchone()[0]
            return total > 0
    except sqlite3.Error:
        return False


async def ensure_sample_datasource(db: AsyncSession) -> DataSource | None:
    settings = get_settings()
    if not settings.sample_seed_enabled:
        return None

    existing = (await db.execute(select(func.count()).select_from(DataSource))).scalar_one()
    if existing:
        return None

    owner = (
        await db.execute(select(User).where(User.role == ROLE_ADMIN).limit(1))
    ).scalar_one_or_none()
    if owner is None:
        return None

    ensure_dir(SAMPLE_DIR)
    db_path = SAMPLE_DIR / "shop.db"
    if not _sample_db_usable(db_path):
        info = build_all(SAMPLE_DIR)
        logger.info("已生成样例数据 %s", info)

    config = {
        "db_path": str(db_path),
        "description": "4 城市 × 3 渠道 × 5 产品，2026-01 ~ 2026-10 的订单/产品/客户",
        "seeded": True,
    }
    datasource = DataSource(
        name=SAMPLE_NAME,
        type="sqlite",
        config=json.dumps(config, ensure_ascii=False),
        owner_id=owner.id,
    )
    db.add(datasource)
    await db.commit()

    # 立刻把 schema / 画像算出来，否则列表页会显示"0 张表"，用户以为数据没进来
    try:
        from app.datasource.factory import create_datasource
        from app.services.profiling import profile_datasource
        from app.services.schema import describe_schema

        connector = create_datasource("sqlite", config)
        await connector.connect()
        try:
            schema = await describe_schema(connector, use_cache=False)
            profile = await profile_datasource(connector)
        finally:
            await connector.disconnect()
        datasource.table_schema = json.dumps(schema, ensure_ascii=False, default=str)
        datasource.profile_json = json.dumps(profile, ensure_ascii=False, default=str)
        await db.commit()
    except Exception:  # noqa: BLE001 - 播种失败不影响启动，下次问答时会重算
        logger.warning("样例数据 schema 预计算失败", exc_info=True)

    logger.info("已播种样例数据源 id=%s", datasource.id)
    return datasource


async def ensure_sample_csv() -> Path | None:
    """把待清洗 CSV 放到 samples 目录，演示上传用。"""
    ensure_dir(SAMPLE_DIR)
    path = SAMPLE_DIR / "门店经营明细_待清洗.csv"
    if not path.exists():
        build_all(SAMPLE_DIR)
    return path
