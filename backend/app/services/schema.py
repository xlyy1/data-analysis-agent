"""把列的样本取值附加到 schema，避免模型把问句里的词直接当过滤值。

留出集暴露的问题：问"黄金会员"，模型写 WHERE 会员等级='黄金会员'，而列里存的是"黄金"。
模型只看得到列名和类型，看不到取值。这里为低基数列补充 sample_values。
"""
from __future__ import annotations

from typing import Any

TEXT_HINTS = ("TEXT", "CHAR", "VARCHAR", "STRING", "OBJECT")
MAX_SAMPLE = 20


def _is_text(dtype: str | None) -> bool:
    text = (dtype or "").upper()
    return any(hint in text for hint in TEXT_HINTS)


async def _sample_values(connector: Any, table: str, column: str) -> list | None:
    """取低基数列的去重取值；高基数或失败时返回 None。"""
    sql = (
        f'SELECT DISTINCT "{column}" FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL LIMIT {MAX_SAMPLE + 1}'
    )
    try:
        result = await connector.execute_query(sql)
    except Exception:  # noqa: BLE001
        return None
    values = [row[0] for row in result.rows]
    if not values or len(values) > MAX_SAMPLE:
        return None
    return values


async def describe_schema(connector: Any) -> dict:
    """构建 schema 描述；文本列附带样本取值。"""
    tables = await connector.get_tables()
    described = []
    for table in tables:
        columns = []
        for column in table.columns:
            entry: dict[str, Any] = {"name": column.name, "dtype": column.dtype}
            if _is_text(column.dtype):
                values = await _sample_values(connector, table.name, column.name)
                if values is not None:
                    entry["sample_values"] = values
            columns.append(entry)
        described.append({"name": table.name, "columns": columns, "row_count": table.row_count})
    return {"tables": described}
