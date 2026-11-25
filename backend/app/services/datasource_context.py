"""把数据源转成 Agent 需要的 (ids, schemas, configs)。

对话接口和定时任务都要用同一套逻辑，抽出来避免两份实现慢慢跑偏。
schema 优先现连现取（带 TTL 缓存），连不上就退回库里的缓存。
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.datasource.factory import create_datasource
from app.models.datasource import DataSource
from app.services.schema import describe_schema


async def resolve_datasource_context(
    db: AsyncSession,
    datasource_ids: list[str],
    *,
    fallback_to_all: bool = True,
    persist_schema: bool = True,
) -> tuple[list[str], list[str], list[str]]:
    ids = [item for item in datasource_ids if item]
    if not ids and fallback_to_all:
        rows = (
            await db.execute(select(DataSource.id).where(DataSource.is_active == True))  # noqa: E712
        ).all()
        ids = [row[0] for row in rows]
    if not ids:
        return [], [], []

    sources = (
        await db.execute(
            select(DataSource).where(
                DataSource.id.in_(ids), DataSource.is_active == True  # noqa: E712
            )
        )
    ).scalars().all()

    schemas: list[str] = []
    configs: list[str] = []
    for ds in sources:
        cfg = json.loads(ds.config) if isinstance(ds.config, str) else (ds.config or {})
        configs.append(json.dumps({"type": ds.type, "config": cfg}, ensure_ascii=False))
        try:
            connector = create_datasource(ds.type, cfg)
            await connector.connect()
            if hasattr(connector, "auto_add_total_columns"):
                connector.auto_add_total_columns()
            try:
                schema_obj = await describe_schema(connector)
            finally:
                await connector.disconnect()
            if persist_schema:
                ds.table_schema = json.dumps(schema_obj, ensure_ascii=False, default=str)
                await db.commit()
            schemas.append(json.dumps(schema_obj, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001 - 单个源不可用不应阻断整次分析
            if ds.table_schema:
                schemas.append(ds.table_schema)
    return [ds.id for ds in sources], schemas, configs
