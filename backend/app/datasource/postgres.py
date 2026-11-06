"""PostgreSQL 数据源适配器"""

import time
from app.datasource.base import BaseDataSource, TableInfo, ColumnInfo, QueryResult
from app.config import get_settings


class PostgresDataSource(BaseDataSource):
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self._pool = None

    @property
    def source_type(self) -> str:
        return "postgres"

    async def connect(self) -> None:
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                min_size=1,
                max_size=5,
            )
        except ImportError:
            raise ImportError("asyncpg is required for PostgreSQL. Install: pip install asyncpg")

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    async def get_tables(self) -> list[TableInfo]:
        tables = []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
            table_names = [r["table_name"] for r in rows]

            for tname in table_names:
                col_rows = await conn.fetch(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name=$1",
                    tname,
                )
                cols = [ColumnInfo(name=c["column_name"], dtype=c["data_type"], nullable=c["is_nullable"] == "YES") for c in col_rows]

                count = await conn.fetchval(f'SELECT COUNT(*) FROM "{tname}"')

                tables.append(TableInfo(name=tname, columns=cols, row_count=count))
        return tables

    async def execute_query(self, sql: str, params: dict | None = None) -> QueryResult:
        start = time.perf_counter()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)
            columns = list(rows[0].keys()) if rows else []

        elapsed = (time.perf_counter() - start) * 1000

        settings = get_settings()
        limited_rows = rows[: settings.max_return_rows]

        str_rows = [[str(v) if v is not None else None for v in dict(r).values()] for r in limited_rows]

        return QueryResult(
            columns=columns,
            rows=str_rows,
            row_count=len(limited_rows),
            elapsed_ms=round(elapsed, 1),
            query=sql,
        )
