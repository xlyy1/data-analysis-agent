"""查询结果的确定性校验：数值域 + 分组对账。

设计原则：
- 不依赖模型，纯规则/数学恒等式
- 检查不出问题时不打扰用户（warnings 为空）
- 对账失败（SQL 太复杂无法构造总计）时静默跳过，不误报
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 列名 → 语义分类
RATE_HINTS = ("率", "占比", "比例", "rate", "ratio", "pct", "percent")
MONEY_HINTS = ("金额", "收入", "营收", "销售额", "利润", "成本", "amount", "revenue", "profit", "cost", "sales")
COUNT_HINTS = ("数量", "销量", "件数", "单量", "qty", "quantity", "count", "num")
GROWTH_HINTS = ("增长", "增速", "同比", "环比", "growth")

SUM_RE = re.compile(r"\bSUM\s*\(\s*([^()]+?)\s*\)", re.I)
FROM_RE = re.compile(r"\bFROM\b(.*?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", re.I | re.S)
WHERE_RE = re.compile(r"\bWHERE\b(.*?)(?:\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", re.I | re.S)
GROUP_RE = re.compile(r"\bGROUP\s+BY\b", re.I)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _classify(column: str) -> str:
    name = str(column).lower()
    # 先判更具体的语义："增长率"同时含"率"，必须先归类为 growth
    if any(h in name for h in GROWTH_HINTS):
        return "growth"
    if any(h in name for h in RATE_HINTS):
        return "rate"
    if any(h in name for h in COUNT_HINTS):
        return "count"
    if any(h in name for h in MONEY_HINTS):
        return "money"
    return "other"


def check_numeric_domains(columns: List[str], rows: List[List[Any]]) -> List[Dict[str, str]]:
    """数值域检查：比率越界、数量为负、增长异常。"""
    warnings: List[Dict[str, str]] = []
    if not columns or not rows:
        return warnings

    for index, column in enumerate(columns):
        kind = _classify(column)
        if kind == "other":
            continue
        values = [row[index] for row in rows if index < len(row) and _is_number(row[index])]
        if not values:
            continue

        if kind == "rate":
            over = [v for v in values if abs(v) > 1]
            if over:
                warnings.append({
                    "level": "warn",
                    "column": str(column),
                    "message": f"「{column}」出现绝对值大于 1 的值（{over[0]:.4g}），"
                               f"可能是百分数未除以基数",
                })
        elif kind == "count":
            negatives = [v for v in values if v < 0]
            if negatives:
                warnings.append({
                    "level": "warn",
                    "column": str(column),
                    "message": f"「{column}」出现负值（{negatives[0]:.4g}），数量类指标不应为负",
                })
        elif kind == "growth":
            extreme = [v for v in values if abs(v) > 10]
            if extreme:
                warnings.append({
                    "level": "warn",
                    "column": str(column),
                    "message": f"「{column}」出现极端值（{extreme[0]:.4g}），"
                               f"可能是分母接近 0 或重复累加",
                })
    return warnings


def check_group_nulls(columns: List[str], rows: List[List[Any]]) -> List[Dict[str, str]]:
    """分组列为空：通常意味着有记录没被归到任何分组。"""
    warnings: List[Dict[str, str]] = []
    for index, column in enumerate(columns):
        nulls = sum(1 for row in rows if index < len(row) and (row[index] is None or row[index] == ""))
        if nulls:
            warnings.append({
                "level": "info",
                "column": str(column),
                "message": f"「{column}」有 {nulls} 行为空，可能有记录未归入任何分组",
            })
    return warnings


def build_total_sql(sql: str) -> Optional[str]:
    """从分组聚合 SQL 推导"总计"查询；无法安全推导时返回 None。"""
    if not sql or not GROUP_RE.search(sql):
        return None

    sums = SUM_RE.findall(sql)
    if len(sums) != 1:
        return None

    from_match = FROM_RE.search(sql)
    if not from_match:
        return None
    source = from_match.group(1).strip()
    if not source or "(" in source:
        # 子查询/派生表不推导，避免构造出错误的总计
        return None

    where_match = WHERE_RE.search(sql)
    where_clause = f" WHERE {where_match.group(1).strip()}" if where_match else ""
    return f"SELECT SUM({sums[0].strip()}) AS __total FROM {source}{where_clause}"


def reconcile(grouped_total: Optional[float], absolute_total: Optional[float],
              tolerance: float = 0.01) -> List[Dict[str, str]]:
    """对账：分组汇总与总计必须相等（相对误差容忍 tolerance）。"""
    if grouped_total is None or absolute_total is None:
        return []

    scale = max(abs(grouped_total), abs(absolute_total), 1e-9)
    diff = abs(grouped_total - absolute_total) / scale
    if diff <= tolerance:
        return []
    return [{
        "level": "warn",
        "column": "__total__",
        "message": f"对账不一致：分组之和 {grouped_total:.4g} 与总计 {absolute_total:.4g} "
                   f"相差 {diff * 100:.1f}%，可能漏分组或过滤条件不一致",
    }]


def numeric_columns(columns: List[str], rows: List[List[Any]]) -> List[int]:
    """返回所有值都是数字的列下标。"""
    indexes = []
    for index in range(len(columns)):
        values = [row[index] for row in rows if index < len(row)]
        if values and all(_is_number(v) for v in values):
            indexes.append(index)
    return indexes
