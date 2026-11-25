"""把列的样本取值附加到 schema，避免模型把问句里的词直接当过滤值。

留出集暴露的问题：问"黄金会员"，模型写 WHERE 会员等级='黄金会员'，而列里存的是"黄金"。
模型只看得到列名和类型，看不到取值。这里为低基数列补充 sample_values。

同时推断表关系（relations / column_lookup / role）并做 TTL 缓存，供 SQL 生成提示使用。
"""
from __future__ import annotations

import copy
import hashlib
import os
import time
from typing import Any

TEXT_HINTS = ("TEXT", "CHAR", "VARCHAR", "STRING", "OBJECT")
MAX_SAMPLE = 20

# 纯通用名不做外键推断，避免 id/code 在不同表间值域重合造成误判。
GENERIC_IDENTIFIERS = {
    "id", "uuid", "guid", "code", "no", "number", "pk", "rowid",
    "编号", "序号", "主键", "创建时间", "更新时间",
    "created_at", "updated_at", "create_time", "update_time",
}
# 业务外键常见后缀：命中则置信度标 high，否则 medium。
FK_SUFFIXES = ("_id", "编码", "编号", "代码")

SCHEMA_CACHE_TTL = float(os.getenv("SCHEMA_CACHE_TTL_SECONDS", "300"))
_SCHEMA_CACHE: dict[str, tuple[float, dict]] = {}


def _cache_key(connector: Any) -> str | None:
    source = getattr(connector, "source_type", "unknown")
    for attr in ("db_path", "file_path"):
        value = getattr(connector, attr, None)
        if value:
            return f"{source}:{value}"
    if getattr(connector, "file_name", None):
        content = getattr(connector, "file_content", None)
        digest = hashlib.sha1(content).hexdigest()[:12] if content else "nopath"
        return f"{source}:{connector.file_name}:{digest}"
    if all(hasattr(connector, attr) for attr in ("host", "port", "database")):
        return f"{source}:{connector.host}:{connector.port}/{connector.database}"
    return None


def invalidate_schema_cache(key: str | None = None) -> None:
    """表结构变更后主动失效；不传 key 清空全部。"""
    if key is None:
        _SCHEMA_CACHE.clear()
    else:
        _SCHEMA_CACHE.pop(key, None)


def _cache_get(key: str) -> dict | None:
    entry = _SCHEMA_CACHE.get(key)
    if not entry:
        return None
    created, value = entry
    if time.monotonic() - created > SCHEMA_CACHE_TTL:
        _SCHEMA_CACHE.pop(key, None)
        return None
    return copy.deepcopy(value)


def _cache_put(key: str, value: dict) -> None:
    _SCHEMA_CACHE[key] = (time.monotonic(), copy.deepcopy(value))


def _is_text(dtype: str | None) -> bool:
    text = (dtype or "").upper()
    return any(hint in text for hint in TEXT_HINTS)


def _is_fk_candidate(column: str) -> bool:
    name = column.strip().lower()
    return bool(name) and name not in GENERIC_IDENTIFIERS


def _fk_confidence(column: str) -> str:
    name = column.strip().lower()
    return "high" if name.endswith(FK_SUFFIXES) else "medium"


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


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _count(connector: Any, sql: str) -> int:
    result = await connector.execute_query(sql)
    if not result.rows:
        return 0
    try:
        return int(float(result.rows[0][0]))
    except (TypeError, ValueError):
        return 0


async def _infer_relations(connector: Any, tables: list[dict]) -> list[dict]:
    """Infer many-to-one relations without declared foreign keys.

    规则：同名列 + 右表唯一 + 左表取值是右表子集。
    纯通用名（id/code/编号…）跳过；业务后缀（_id/编码/编号/代码）标 high。
    """
    relations: list[dict] = []
    for left in tables:
        left_cols = [c["name"] for c in left["columns"]]
        for right in tables:
            if right["name"] == left["name"]:
                continue
            right_cols = [c["name"] for c in right["columns"]]
            for column in sorted(set(left_cols) & set(right_cols)):
                if not _is_fk_candidate(column):
                    continue
                col = _quote_ident(column)
                right_distinct = await _count(
                    connector,
                    f"SELECT COUNT(DISTINCT {col}) FROM {_quote_ident(right['name'])} "
                    f"WHERE {col} IS NOT NULL",
                )
                if right_distinct != right["row_count"]:
                    continue
                missing = await _count(
                    connector,
                    "SELECT COUNT(*) FROM ("
                    f"SELECT DISTINCT {col} FROM {_quote_ident(left['name'])} WHERE {col} IS NOT NULL "
                    f"EXCEPT SELECT {col} FROM {_quote_ident(right['name'])})",
                )
                if missing:
                    continue
                relations.append({
                    "left": f"{left['name']}.{column}",
                    "right": f"{right['name']}.{column}",
                    "type": "many-to-one",
                    "confidence": _fk_confidence(column),
                })
    return relations


async def describe_schema(connector: Any, *, use_cache: bool = True) -> dict:
    """构建 schema 描述；文本列附带样本取值，结果按数据源缓存 TTL 秒。"""
    key = _cache_key(connector) if use_cache else None
    if key:
        cached = _cache_get(key)
        if cached is not None:
            return cached

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
    for table in described:
        table["role"] = "dimension" if table["row_count"] < 1000 else "fact"
    relations = await _infer_relations(connector, described)
    column_lookup: dict[str, list[str]] = {}
    for table in described:
        for column in table["columns"]:
            column_lookup.setdefault(column["name"], []).append(table["name"])

    result = {
        "tables": described,
        "relations": relations,
        "column_lookup": column_lookup,
        "join_hint": (
            "维度字段常在 dimension 表：先查 column_lookup 确认字段属于哪张表；"
            "字段不在 fact 表时，按 relations 用 JOIN 关联，不要直接写在不含该字段的表上。"
        ),
    }
    if key:
        _cache_put(key, result)
    return result
