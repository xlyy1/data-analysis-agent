"""SQL execution node — runs generated SQL on real datasources.

Also automatically computes "total" columns by grouping columns that share a common suffix,
so the LLM can simply query "总销量" instead of manually summing "京东销量"+"天猫销量"+"拼多多销量".

多数据源并行取数，单个源超时后重试一次（`query_timeout_seconds` / `query_retries`）。
"""

import asyncio
import json

from app.agent.state import AgentState
from app.agent.validators import (
    build_total_sql,
    check_group_nulls,
    check_numeric_domains,
    numeric_columns,
    reconcile,
)
from app.config import get_settings
from app.datasource.factory import create_datasource
from app.observability.metrics import sql_executed_total, sql_guarded_total
from app.services.resilience import run_with_retry
from app.services.sql_policy import cap_cells, guard_sql
from app.services.sql_validator import validate_sql_columns


def _datasource_label(cfg_str) -> str:
    try:
        cfg = json.loads(cfg_str) if isinstance(cfg_str, str) else cfg_str
        return str(cfg.get("type", "?"))
    except Exception:  # noqa: BLE001
        return "?"


async def _query_one(cfg_str: str, sql: str):
    """在单个数据源上执行，超时重试；返回 (result, 实际执行的 sql, 连接器)。"""
    settings = get_settings()
    cfg = json.loads(cfg_str) if isinstance(cfg_str, str) else cfg_str

    async def attempt():
        connector = create_datasource(cfg["type"], cfg["config"])
        await connector.connect()
        try:
            local_sql = sql
            if hasattr(connector, "auto_add_total_columns"):
                totals = connector.auto_add_total_columns()
                if totals:
                    local_sql = _rewrite_sql_with_totals(sql, totals)
            result = await connector.execute_query(local_sql)
            return result, local_sql, connector
        except BaseException:
            # 失败/超时被取消的那一次尝试也必须关连接，否则重试会持续泄漏
            # SQLite 文件句柄（表现为大量 ResourceWarning: unclosed database）。
            try:
                await connector.disconnect()
            except Exception:  # noqa: BLE001
                pass
            raise

    payload, attempts = await run_with_retry(
        attempt,
        timeout=settings.query_timeout_seconds,
        retries=settings.query_retries,
    )
    return payload, attempts


async def execute_query(state: AgentState) -> AgentState:
    sql = state.get("generated_sql", "")
    configs = state.get("datasource_configs", [])

    if not sql:
        return {**state, "error": "No SQL to execute"}

    if not configs:
        return {**state, "error": "No datasource configs available"}

    # 硬约束：执行前校验列归属，未知列/维度字段未 JOIN 直接打回重写。
    schemas = state.get("datasource_schemas", [])
    if sql and len(configs) == 1 and schemas:
        try:
            raw = schemas[0]
            schema = json.loads(raw) if isinstance(raw, str) else raw
            valid, message = validate_sql_columns(sql, schema)
        except Exception:  # noqa: BLE001
            valid, message = True, ""
        if not valid:
            return {
                **state,
                "error": message,
                "sql_error": message,
                "sql_retry_count": state.get("sql_retry_count", 0) + 1,
            }

    settings = get_settings()

    # 硬约束 2：只读 / 单语句 / 长度上限 / 自动 LIMIT。
    # 这是最后一道闸：即使模型被 prompt 注入带偏，也写不了库。
    decision = guard_sql(
        sql,
        max_chars=settings.sql_max_chars,
        default_limit=settings.sql_default_limit,
        allow_write=bool(state.get("allow_write")) and settings.sql_allow_write_for_admin,
    )
    if not decision.ok:
        sql_guarded_total.inc(reason=decision.code)
        return {
            **state,
            "error": decision.as_error(),
            "sql_error": decision.as_error(),
            "sql_retry_count": state.get("sql_retry_count", 0) + 1,
        }
    if decision.applied_limit:
        sql_guarded_total.inc(reason="sql_limit_appended")
    # 后续执行用规整后的 SQL（已补 LIMIT），状态里的 generated_sql 保留原文给用户看
    sql = decision.sql

    # 多数据源并行：任一源成功即可继续，避免慢源拖住整条链路
    if settings.parallel_datasources and len(configs) > 1:
        outcomes = await asyncio.gather(
            *[_query_one(cfg_str, sql) for cfg_str in configs],
            return_exceptions=True,
        )
    else:
        outcomes = []
        for cfg_str in configs:
            try:
                outcomes.append(await _query_one(cfg_str, sql))
            except Exception as error:  # noqa: BLE001
                outcomes.append(error)

    errors: list[str] = []
    # 先完整记录每个源的成败，避免提前 return 时状态不全
    status: list[dict] = []
    for cfg_str, outcome in zip(configs, outcomes, strict=False):
        label = _datasource_label(cfg_str)
        if isinstance(outcome, BaseException):
            errors.append(f"{label}: {outcome}")
            status.append({"datasource": label, "ok": False, "error": str(outcome)[:120]})
        else:
            status.append({"datasource": label, "ok": True})

    for cfg_str, outcome in zip(configs, outcomes, strict=False):
        if isinstance(outcome, BaseException):
            continue

        (result, executed_sql, connector), _attempts = outcome
        warnings = check_numeric_domains(result.columns, result.rows)
        warnings += check_group_nulls(result.columns, result.rows)

        total_sql = build_total_sql(executed_sql)
        if total_sql and result.rows:
            try:
                total_result = await asyncio.wait_for(
                    connector.execute_query(total_sql),
                    timeout=settings.query_timeout_seconds,
                )
                absolute = None
                if total_result.rows and total_result.rows[0]:
                    absolute = total_result.rows[0][0]
                numeric = numeric_columns(result.columns, result.rows)
                if numeric and absolute is not None:
                    column_index = numeric[0]
                    grouped = sum(
                        row[column_index] for row in result.rows
                        if column_index < len(row) and isinstance(row[column_index], (int, float))
                    )
                    warnings += reconcile(grouped, absolute)
            except Exception:
                # 对账查询失败不影响主流程，静默跳过
                pass
        try:
            await connector.disconnect()
        except Exception:  # noqa: BLE001
            pass

        # 硬约束 3：行数 / 单元格上限，宽表按列数折算，避免一次分析把内存打满
        max_rows = cap_cells(
            len(result.columns),
            settings.max_return_rows,
            max_cells=settings.sql_max_result_cells,
        )
        rows = result.rows[:max_rows] if max_rows else result.rows
        if len(rows) < len(result.rows):
            warnings.append({
                "level": "info",
                "column": "__truncated__",
                "message": (
                    f"结果共 {len(result.rows)} 行，按行数上限展示前 {len(rows)} 行；"
                    "需要完整数据请缩小查询范围或加筛选条件"
                ),
            })

        query_result = {
            "columns": result.columns,
            "rows": rows,
            "row_count": len(rows),
            "total_row_count": len(result.rows),
            "elapsed_ms": result.elapsed_ms,
            "executed_sql": executed_sql,
        }
        sql_executed_total.inc(datasource_type=_datasource_label(cfg_str))

        # 部分成功：有源失败但至少一个成功时，继续出结果并明确告警，
        # 不让个别源不可用拖垮整次分析。
        failed = [item["datasource"] for item in status if not item["ok"]]
        for name in failed:
            warnings.append({
                "level": "warn",
                "column": "__datasource__",
                "message": f"数据源「{name}」取数失败，本次结果未包含该源数据",
            })

        return {
            **state,
            "query_result_json": json.dumps(query_result, ensure_ascii=False),
            "error": "",
            "empty_result": result.row_count == 0,
            "result_warnings": warnings,
            "datasource_status": status,
        }

    message = f"SQL execution failed: {'; '.join(errors)}"
    return {
        **state,
        "error": message,
        "sql_error": message,
        "sql_retry_count": state.get("sql_retry_count", 0) + 1,
        "datasource_status": status,
    }


def _rewrite_sql_with_totals(sql: str, totals: dict[str, list[str]]) -> str:
    """Replace manual column summation with computed total columns.

    For example, if totals={"总销量": ["京东销量","天猫销量","拼多多销量"]},
    replace `"京东销量" + "天猫销量" + "拼多多销量"` with `"总销量"`.

    Also handles `SUM("京东销量" + "天猫销量" + "拼多多销量")` → `SUM("总销量")`.
    """

    for total_col, member_cols in totals.items():
        members_sorted = sorted(member_cols, key=len, reverse=True)

        # Build patterns: "col1" + "col2" + "col3"  or  "col1"+"col2"+"col3"
        addition = ' + '.join(f'"{c}"' for c in members_sorted)
        if addition in sql:
            sql = sql.replace(addition, f'"{total_col}"')
        else:
            # Try each permutation (LLM may sum them in any order)
            for perm_cols in [member_cols, list(reversed(member_cols))]:
                addition_alt = ' + '.join(f'"{c}"' for c in perm_cols)
                if addition_alt in sql:
                    sql = sql.replace(addition_alt, f'"{total_col}"')
                    break

    return sql
