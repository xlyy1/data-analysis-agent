"""SQLite 数据源适配器 (连接外部 SQLite 文件)"""

import time
import aiosqlite
from pathlib import Path

from app.datasource.base import BaseDataSource, TableInfo, ColumnInfo, QueryResult
from app.config import get_settings


class SQLiteDataSource(BaseDataSource):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    @property
    def source_type(self) -> str:
        return "sqlite"

    async def connect(self) -> None:
        path = Path(self.db_path)
        if not path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
        self._conn = await aiosqlite.connect(str(path))
        self._conn.row_factory = aiosqlite.Row

    async def disconnect(self) -> None:
        if self._conn:
            await self._conn.close()

    async def get_tables(self) -> list[TableInfo]:
        tables = []
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = [row[0] async for row in cursor]

        for tname in table_names:
            cur = await self._conn.execute(f"PRAGMA table_info('{tname}')")
            cols = [ColumnInfo(name=r[1], dtype=r[2], nullable=not r[3]) async for r in cur]

            cur2 = await self._conn.execute(f"SELECT COUNT(*) FROM '{tname}'")
            row_count = (await cur2.fetchone())[0]

            tables.append(TableInfo(name=tname, columns=cols, row_count=row_count))
        return tables

    async def execute_query(self, sql: str, params: dict | None = None) -> QueryResult:
        start = time.perf_counter()
        cursor = await self._conn.execute(sql)
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        elapsed = (time.perf_counter() - start) * 1000

        settings = get_settings()
        limited_rows = rows[: settings.max_return_rows]

        str_rows = [[str(v) if v is not None else None for v in tuple(dict(r).values())] for r in limited_rows]

        return QueryResult(
            columns=columns,
            rows=str_rows,
            row_count=len(limited_rows),
            elapsed_ms=round(elapsed, 1),
            query=sql,
        )
