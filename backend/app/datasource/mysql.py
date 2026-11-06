"""MySQL 数据源适配器"""

import time
import asyncio
from contextlib import asynccontextmanager

from app.datasource.base import BaseDataSource, TableInfo, ColumnInfo, QueryResult
from app.config import get_settings


class MySQLDataSource(BaseDataSource):
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self._pool = None

    @property
    def source_type(self) -> str:
        return "mysql"

    async def connect(self) -> None:
        try:
            import aiomysql

            self._pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                minsize=1,
                maxsize=5,
                autocommit=True,
            )
        except ImportError:
            raise ImportError("aiomysql is required for MySQL connection. Install: pip install aiomysql")

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    async def get_tables(self) -> list[TableInfo]:
        tables = []
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SHOW TABLES")
                table_names = [row[0] async for row in cur]

            for tname in table_names:
                async with conn.cursor() as cur:
                    await cur.execute(f"DESCRIBE `{tname}`")
                    cols = [ColumnInfo(name=row[0], dtype=row[1], nullable=row[2] == "YES") async for row in cur]

                async with conn.cursor() as cur:
                    await cur.execute(f"SELECT COUNT(*) FROM `{tname}`")
                    row_count = (await cur.fetchone())[0]

                tables.append(TableInfo(name=tname, columns=cols, row_count=row_count))
        return tables

    async def execute_query(self, sql: str, params: dict | None = None) -> QueryResult:
        start = time.perf_counter()
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
                columns = [d[0] for d in cur.description] if cur.description else []

        elapsed = (time.perf_counter() - start) * 1000

        # 行数限制
        settings = get_settings()
        limited_rows = rows[: settings.max_return_rows]

        str_rows = [[str(v) if v is not None else None for v in row] for row in limited_rows]

        return QueryResult(
            columns=columns,
            rows=str_rows,
            row_count=len(limited_rows),
            elapsed_ms=round(elapsed, 1),
            query=sql,
        )
