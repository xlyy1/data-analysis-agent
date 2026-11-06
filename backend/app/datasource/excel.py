"""Excel / CSV 数据源

上传的文件会被解析为 SQLite 内存数据库中的表，通过 SQL 查询。
"""

import io
import time
import pandas as pd
from pathlib import Path

from app.datasource.base import BaseDataSource, TableInfo, ColumnInfo, QueryResult


class ExcelDataSource(BaseDataSource):
    """Excel/CSV 文件数据源 — 加载到 SQLite 内存库"""

    def __init__(self, file_path: str | None = None, file_content: bytes | None = None, file_name: str = "data"):
        self.file_path = file_path
        self.file_content = file_content
        self.file_name = file_name
        self._dfs: dict[str, pd.DataFrame] = {}

    @property
    def source_type(self) -> str:
        suffix = Path(self.file_name).suffix.lower()
        if suffix == ".csv":
            return "csv"
        return "excel"

    async def connect(self) -> None:
        """解析文件到 DataFrame"""
        import asyncio

        loop = asyncio.get_event_loop()
        suffix = Path(self.file_name).suffix.lower()

        if suffix == ".csv":
            if self.file_content:
                self._dfs[self.file_name] = await loop.run_in_executor(
                    None, lambda: pd.read_csv(io.BytesIO(self.file_content))
                )
            else:
                self._dfs[self.file_name] = await loop.run_in_executor(
                    None, lambda: pd.read_csv(self.file_path)
                )
        else:
            # Excel (xlsx/xls)
            if self.file_content:
                excel_file = await loop.run_in_executor(
                    None, lambda: pd.ExcelFile(io.BytesIO(self.file_content))
                )
            else:
                excel_file = await loop.run_in_executor(None, lambda: pd.ExcelFile(self.file_path))

            for sheet in excel_file.sheet_names:
                self._dfs[sheet] = await loop.run_in_executor(None, lambda s=sheet: excel_file.parse(s))

    async def disconnect(self) -> None:
        self._dfs.clear()

    def auto_add_total_columns(self) -> dict[str, list[str]]:
        """Group numeric columns by common suffix and create '总{suffix}' sum columns.

        Only creates non-overlapping groups — each column belongs to at most one group.
        Longest suffix wins (e.g. "销量"(2) over "量"(1)).
        """
        from collections import defaultdict

        totals_added = {}
        for table_name, df in self._dfs.items():
            cols = list(df.columns)
            numeric_cols = set(c for c in cols if pd.api.types.is_numeric_dtype(df[c]))
            if len(numeric_cols) < 2:
                continue

            # Collect all suffixes (1-4 chars) with their members
            suffix_candidates = defaultdict(list)
            for min_len in range(1, 5):
                for c in numeric_cols:
                    if len(c) >= min_len:
                        suffix_candidates[c[-min_len:]].append(c)

            # Start with longest suffixes, build non-overlapping groups
            used_cols = set()
            for suffix in sorted(suffix_candidates, key=len, reverse=True):
                members = [c for c in suffix_candidates[suffix] if c not in used_cols]
                if len(members) >= 2:
                    total_col = f"总{suffix}"
                    if total_col in cols:
                        continue
                    df[total_col] = df[members].sum(axis=1)
                    used_cols.update(members)
                    totals_added[total_col] = members

        return totals_added

    async def get_tables(self) -> list[TableInfo]:
        tables = []
        for name, df in self._dfs.items():
            cols = [ColumnInfo(name=c, dtype=str(df[c].dtype), nullable=True) for c in df.columns]
            tables.append(TableInfo(name=name, columns=cols, row_count=len(df)))
        return tables

    async def execute_query(self, sql: str, params: dict | None = None) -> QueryResult:
        """Execute SQL against in-memory SQLite containing the loaded DataFrames"""
        import asyncio
        import sqlite3

        start = time.perf_counter()

        # Keep EVERYTHING in one thread — sqlite3 objects are thread-bound
        def _query():
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            try:
                for name, df in self._dfs.items():
                    df.to_sql(name, conn, index=False, if_exists="replace")
                cur = conn.execute(sql)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
                return rows, cols
            finally:
                conn.close()

        rows, columns = await asyncio.get_event_loop().run_in_executor(None, _query)

        elapsed = (time.perf_counter() - start) * 1000
        str_rows = [[str(v) if v is not None else None for v in row] for row in rows]

        return QueryResult(
            columns=list(columns) if columns else [],
            rows=str_rows,
            row_count=len(rows),
            elapsed_ms=round(elapsed, 1),
            query=sql,
        )
