"""Schema profiling：给每张表/每列算数据质量画像。

为什么需要：LLM 只看列名和类型，不知道"这列 60% 是空""这列是唯一键""这列存的是
手机号"。把这些事实显式算出来，既能提升 NL2SQL 的准确率，也能在上传后立刻把
"数据不可用"的问题暴露给用户，而不是等到分析结果离谱才回头查。

实现上按表聚合（一条 SQL 拿全列的 COUNT/MIN/MAX/DISTINCT），再对低基数列补
TOP 值，避免逐列扫表。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.datasource.base import BaseDataSource

PII_PATTERNS = {
    "phone": re.compile(r"手机|电话|mobile|phone|tel", re.IGNORECASE),
    "email": re.compile(r"邮箱|email|mail", re.IGNORECASE),
    "id_card": re.compile(r"身份证|id_card|idcard|证件号", re.IGNORECASE),
    "address": re.compile(r"地址|address|住址", re.IGNORECASE),
    "name": re.compile(r"^姓名$|客户名|联系人|contact_name", re.IGNORECASE),
}
NUMERIC_HINTS = ("INT", "REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "BIGINT", "SMALLINT")
TOP_VALUE_LIMIT = 5
LOW_CARDINALITY = 30


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    non_null: int = 0
    null_count: int = 0
    null_rate: float = 0.0
    distinct_count: int = 0
    distinct_rate: float = 0.0
    min_value: Any = None
    max_value: Any = None
    top_values: list[dict] = field(default_factory=list)
    is_numeric: bool = False
    is_unique: bool = False
    is_pii: bool = False
    pii_kind: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "non_null": self.non_null,
            "null_count": self.null_count,
            "null_rate": round(self.null_rate, 4),
            "distinct_count": self.distinct_count,
            "distinct_rate": round(self.distinct_rate, 4),
            "min": self.min_value,
            "max": self.max_value,
            "top_values": self.top_values,
            "is_numeric": self.is_numeric,
            "is_unique": self.is_unique,
            "is_pii": self.is_pii,
            "pii_kind": self.pii_kind,
        }


def _quote(connector: BaseDataSource, name: str) -> str:
    quote = "`" if getattr(connector, "source_type", "") == "mysql" else '"'
    escaped = name.replace(quote, quote * 2)
    return f"{quote}{escaped}{quote}"


def _pii_kind(column: str) -> str:
    for kind, pattern in PII_PATTERNS.items():
        if pattern.search(column):
            return kind
    return ""


def _is_numeric(dtype: str) -> bool:
    text = (dtype or "").upper()
    return any(hint in text for hint in NUMERIC_HINTS)


async def profile_table(
    connector: BaseDataSource,
    table: str,
    *,
    table_info: Any = None,
    row_count: int = 0,
    top_values: int = TOP_VALUE_LIMIT,
) -> dict:
    """单表画像。聚合失败时返回带 error 的占位结果，不抛给调用方。"""
    if table_info is None:
        tables = {t.name: t for t in await connector.get_tables()}
        table_info = tables.get(table)
    info = table_info
    if info is None:
        return {"table": table, "error": "表不存在", "columns": []}
    if not row_count:
        row_count = info.row_count

    aggregates = ["COUNT(*)"]
    for column in info.columns:
        quoted = _quote(connector, column.name)
        aggregates.extend(
            [f"COUNT({quoted})", f"COUNT(DISTINCT {quoted})", f"MIN({quoted})", f"MAX({quoted})"]
        )
    sql = f"SELECT {', '.join(aggregates)} FROM {_quote(connector, table)}"
    try:
        result = await connector.execute_query(sql)
        values = result.rows[0] if result.rows else []
    except Exception as error:  # noqa: BLE001
        return {"table": table, "error": str(error)[:200], "columns": []}

    total = int(values[0] or 0) if values else row_count
    columns: list[ColumnProfile] = []
    for index, column in enumerate(info.columns):
        base = 1 + index * 4
        non_null = int(values[base] or 0) if len(values) > base else 0
        distinct = int(values[base + 1] or 0) if len(values) > base + 1 else 0
        profile = ColumnProfile(
            name=column.name,
            dtype=column.dtype,
            non_null=non_null,
            null_count=max(0, total - non_null),
            null_rate=(total - non_null) / total if total else 0.0,
            distinct_count=distinct,
            distinct_rate=distinct / total if total else 0.0,
            min_value=values[base + 2] if len(values) > base + 2 else None,
            max_value=values[base + 3] if len(values) > base + 3 else None,
            is_numeric=_is_numeric(column.dtype),
            is_unique=bool(total) and distinct == total,
        )
        profile.pii_kind = _pii_kind(column.name)
        profile.is_pii = bool(profile.pii_kind)
        if 1 <= distinct <= LOW_CARDINALITY:
            profile.top_values = await _top_values(connector, table, column.name, top_values)
        columns.append(profile)

    duplicates = 0
    if total:
        try:
            cols = ", ".join(_quote(connector, c.name) for c in info.columns)
            dup_sql = (
                f"SELECT COUNT(*) FROM (SELECT {cols} FROM {_quote(connector, table)} "
                f"GROUP BY {cols} HAVING COUNT(*) > 1)"
            )
            dup_result = await connector.execute_query(dup_sql)
            duplicates = int(dup_result.rows[0][0]) if dup_result.rows else 0
        except Exception:  # noqa: BLE001 - 部分方言不支持，跳过
            duplicates = 0

    risks: list[str] = []
    for column in columns:
        if column.null_rate >= 0.5:
            risks.append(f"列「{column.name}」缺失率 {column.null_rate:.0%}，按它分组会得到「未知」大类")
        if column.is_pii:
            risks.append(f"列「{column.name}」疑似个人敏感信息（{column.pii_kind}），建议脱敏后再分析")
    if duplicates:
        risks.append(f"存在 {duplicates} 组完全重复的记录，指标可能被重复计算")

    return {
        "table": table,
        "row_count": total,
        "column_count": len(columns),
        "duplicate_groups": duplicates,
        "risks": risks,
        "columns": [column.as_dict() for column in columns],
    }


async def _top_values(
    connector: BaseDataSource, table: str, column: str, limit: int
) -> list[dict]:
    quoted_col = _quote(connector, column)
    sql = (
        f"SELECT {quoted_col}, COUNT(*) FROM {_quote(connector, table)} "
        f"WHERE {quoted_col} IS NOT NULL "
        f"GROUP BY {quoted_col} ORDER BY COUNT(*) DESC LIMIT {int(limit)}"
    )
    try:
        result = await connector.execute_query(sql)
    except Exception:  # noqa: BLE001
        return []
    return [{"value": row[0], "count": row[1]} for row in result.rows]


async def profile_datasource(
    connector: BaseDataSource, *, max_tables: int = 20, include_top_values: bool = True
) -> dict:
    tables = await connector.get_tables()
    limited = tables[:max_tables]
    profiles = []
    for table in limited:
        profiles.append(
            await profile_table(
                connector,
                table.name,
                table_info=table,
                row_count=table.row_count,
                top_values=TOP_VALUE_LIMIT if include_top_values else 0,
            )
        )
    total_rows = sum(table.row_count for table in limited)
    high_risk = sum(len(profile.get("risks") or []) for profile in profiles)
    return {
        "table_count": len(tables),
        "profiled_tables": len(limited),
        "total_rows": total_rows,
        "risk_count": high_risk,
        "tables": profiles,
        "truncated": len(tables) > len(limited),
    }
