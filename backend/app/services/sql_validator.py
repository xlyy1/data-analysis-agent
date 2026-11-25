"""Post-generation SQL column ownership validation.

Conservative: only rejects when it is confident that a quoted identifier is a
known column but not present in any FROM/JOIN table. Skips CTEs, subqueries and
unparseable SQL, so it does not block valid queries with functions or aliases.
"""
from __future__ import annotations

import re

TABLE_RE = re.compile(
    r'\b(?:FROM|JOIN)\s+("?[\w\u4e00-\u9fff]+"?)\s*(?:(?:AS\s+)?([A-Za-z_]\w*))?',
    re.IGNORECASE,
)
QUALIFIED_RE = re.compile(r'("?[\w\u4e00-\u9fff]+"?)\s*\.\s*"([^"]+)"')
UNQUALIFIED_RE = re.compile(r'(?<![\.\w])"([^"]+)"')
ALIAS_RE = re.compile(r'\bAS\s+"[^"]+"', re.IGNORECASE)
LITERAL_RE = re.compile(r"'(?:[^']|'')*'")

RESERVED = {
    "WHERE", "ON", "GROUP", "ORDER", "LIMIT", "JOIN", "LEFT", "RIGHT",
    "INNER", "OUTER", "AS", "HAVING", "UNION", "SET", "USING", "CROSS", "FULL",
}


def _table_map(text: str, tables: dict[str, set[str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for match in TABLE_RE.finditer(text):
        table = match.group(1).strip('"')
        if table not in tables:
            continue
        mapping[table] = table
        alias = match.group(2)
        if alias and alias.upper() not in RESERVED:
            mapping[alias] = table
    return mapping


def validate_sql_columns(sql: str, schema: dict) -> tuple[bool, str]:
    """Return (ok, message). Empty message means no issue found."""
    if not sql or not schema:
        return True, ""
    if re.search(r"\bWITH\b|\(\s*SELECT\b", sql, re.IGNORECASE):
        return True, ""

    tables = {
        table["name"]: {column["name"] for column in table.get("columns", [])}
        for table in schema.get("tables", [])
    }
    lookup = schema.get("column_lookup", {})
    if not tables:
        return True, ""

    text = ALIAS_RE.sub(" ", LITERAL_RE.sub("''", sql))
    mapping = _table_map(text, tables)
    if not mapping:
        return True, ""
    joined = set(mapping.values())

    for match in QUALIFIED_RE.finditer(text):
        alias, column = match.group(1).strip('"'), match.group(2)
        table = mapping.get(alias)
        if not table or column in tables[table]:
            continue
        if column in lookup:
            return False, (
                f'列 "{column}" 不属于表 {table}；它属于 {lookup[column]}，请先 JOIN 对应表。'
            )

    for match in UNQUALIFIED_RE.finditer(text):
        column = match.group(1)
        if any(column in tables[table] for table in joined):
            continue
        if column in lookup:
            suggestions = [table for table in lookup[column] if table in tables]
            return False, (
                f'列 "{column}" 不在已 JOIN 的表 {sorted(joined)} 中；'
                f"它属于 {suggestions}，请先 JOIN 对应表。"
            )

    return True, ""
