"""SQL 安全策略：只读、单语句、长度上限、自动 LIMIT。

模型生成的 SQL 不能直接丢给数据库执行。这一层做四件事：

1. **只读**：只允许 SELECT / WITH / EXPLAIN / SHOW / DESCRIBE。
   写操作（INSERT/UPDATE/DELETE/DDL/COPY/ATTACH/PRAGMA…）一律拒绝，
   默认连管理员也不放行（`SQL_ALLOW_WRITE_FOR_ADMIN=false`）。
2. **单语句**：拒绝分号拼接的多语句，堵 `SELECT 1; DROP TABLE x`。
3. **长度上限**：超长 SQL 直接拒绝，避免拿查询当 CPU 炸弹。
4. **自动 LIMIT**：没有 LIMIT 的查询补一个默认上限，防止一次拉全表。

实现上先把字符串字面量和注释"打码"，再做关键字判定，避免把
`WHERE name='delete me'` 误判成写操作。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 只读语句允许的开头
READ_PREFIXES = ("select", "with", "explain", "show", "describe", "desc")

# 出现即拒绝的关键字（大小写不敏感，匹配的是"打码"后的 SQL）。
# 只收"出现就一定意味着写操作/越权"的词——像 comment、load、lock、analyze 这种
# 也可能是业务列名，收进来会误伤正常查询，所以不放。
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "attach", "detach", "vacuum", "reindex", "pragma",
    "exec", "execute", "merge",
}
# SELECT 里合法但同名于写关键字的函数（按"后面紧跟左括号"放行）
SAFE_FUNCTIONS = {"replace"}


SUSPICIOUS_PATTERNS = (
    (re.compile(r"\binto\s+outfile\b", re.IGNORECASE), "禁止导出到文件"),
    (re.compile(r"\binto\s+dumpfile\b", re.IGNORECASE), "禁止导出到文件"),
    (re.compile(r"\bload_file\s*\(", re.IGNORECASE), "禁止读取服务器文件"),
    (re.compile(r"\bpg_read_file\s*\(", re.IGNORECASE), "禁止读取服务器文件"),
    (re.compile(r"\bxp_cmdshell\b", re.IGNORECASE), "禁止执行系统命令"),
    (re.compile(r"\bsp_configure\b", re.IGNORECASE), "禁止修改服务器配置"),
    (re.compile(r"\bsleep\s*\(\s*\d", re.IGNORECASE), "禁止延时注入"),
    (re.compile(r"\bbenchmark\s*\(", re.IGNORECASE), "禁止压力函数"),
)

_CODE = {
    "empty": "sql_empty",
    "too_long": "sql_too_long",
    "multi_statement": "sql_multi_statement",
    "not_readonly": "sql_not_readonly",
    "write_not_allowed": "sql_write_forbidden",
    "suspicious": "sql_suspicious",
}


@dataclass
class SqlDecision:
    ok: bool
    sql: str
    code: str = ""
    reason: str = ""
    applied_limit: int | None = None
    notes: list[str] = field(default_factory=list)

    def as_error(self) -> str:
        return self.reason or "SQL 未通过安全校验"


def _mask(sql: str) -> str:
    """把字符串字面量与注释替换成空格，只留下可判定的结构。"""
    out: list[str] = []
    i = 0
    length = len(sql)
    while i < length:
        ch = sql[i]
        # 行注释
        if ch == "-" and i + 1 < length and sql[i + 1] == "-":
            while i < length and sql[i] != "\n":
                i += 1
            out.append(" ")
            continue
        # 块注释
        if ch == "/" and i + 1 < length and sql[i + 1] == "*":
            i += 2
            while i + 1 < length and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
            out.append(" ")
            continue
        # 字符串字面量（支持 '' 转义）
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < length:
                if sql[i] == quote:
                    if i + 1 < length and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" '' ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _has_top_level_semicolon(masked: str) -> bool:
    body = masked.rstrip()
    if body.endswith(";"):
        body = body[:-1]
    return ";" in body


def _strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def _needs_limit(masked: str, first_word: str) -> bool:
    if first_word in ("show", "describe", "desc", "explain"):
        return False
    return not re.search(r"\blimit\b", masked, re.IGNORECASE)


def guard_sql(
    sql: str,
    *,
    max_chars: int = 8000,
    default_limit: int = 1000,
    allow_write: bool = False,
) -> SqlDecision:
    """返回是否放行 + 规整后的 SQL。"""
    raw = (sql or "").strip()
    if not raw:
        return SqlDecision(False, "", _CODE["empty"], "没有可执行的 SQL")

    if len(raw) > max_chars:
        return SqlDecision(
            False,
            "",
            _CODE["too_long"],
            f"SQL 过长（{len(raw)} 字符，上限 {max_chars}），请缩小查询范围",
        )

    masked = _mask(raw)
    if _has_top_level_semicolon(masked):
        return SqlDecision(
            False, "", _CODE["multi_statement"], "只允许执行单条 SQL，检测到多条语句"
        )

    first_match = re.match(r"\s*\(?\s*([a-zA-Z]+)", masked)
    first_word = first_match.group(1).lower() if first_match else ""
    if not first_word:
        return SqlDecision(False, "", _CODE["empty"], "无法识别 SQL 语句类型")

    for pattern, reason in SUSPICIOUS_PATTERNS:
        if pattern.search(masked):
            return SqlDecision(False, "", _CODE["suspicious"], reason)

    if first_word not in READ_PREFIXES:
        code = _CODE["not_readonly"] if allow_write else _CODE["write_not_allowed"]
        if allow_write:
            return SqlDecision(False, "", code, f"暂不支持 {first_word.upper()} 语句")
        return SqlDecision(
            False,
            "",
            code,
            f"只允许只读查询，拒绝执行 {first_word.upper()} 语句",
        )

    # WITH 也可能包着写操作（PostgreSQL 的 data-modifying CTE）
    if first_word == "with" and not re.search(r"\bselect\b", masked, re.IGNORECASE):
        return SqlDecision(False, "", _CODE["not_readonly"], "WITH 语句必须包含 SELECT")

    for keyword in FORBIDDEN_KEYWORDS:
        # replace() 是合法字符串函数：只有它后面紧跟 "(" 才放行
        pattern = rf"\b{keyword}\b(?!\s*\()" if keyword in SAFE_FUNCTIONS else rf"\b{keyword}\b"
        if re.search(pattern, masked, re.IGNORECASE):
            return SqlDecision(
                False,
                "",
                _CODE["write_not_allowed"] if not allow_write else _CODE["not_readonly"],
                f"只允许只读查询，检测到被禁止的关键字：{keyword.upper()}",
            )

    cleaned = _strip_trailing_semicolon(raw)
    applied_limit = None
    if _needs_limit(masked, first_word):
        # 换行再拼：SQL 末尾若是一行注释（-- ...），LIMIT 必须落在新行才生效
        cleaned = f"{cleaned}\nLIMIT {int(default_limit)}"
        applied_limit = int(default_limit)

    return SqlDecision(True, cleaned, applied_limit=applied_limit)


def cap_cells(columns: int, rows: int, *, max_cells: int) -> int:
    """返回按列数折算后允许的最大行数，避免宽表把内存打爆。"""
    if columns <= 0:
        return rows
    return max(1, min(rows, max_cells // columns))


__all__ = ["SqlDecision", "cap_cells", "guard_sql"]
