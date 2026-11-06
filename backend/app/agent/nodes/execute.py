"""SQL execution node — runs generated SQL on real datasources.

Also automatically computes "total" columns by grouping columns that share a common suffix,
so the LLM can simply query "总销量" instead of manually summing "京东销量"+"天猫销量"+"拼多多销量".
"""

import json
from app.agent.state import AgentState
from app.datasource.factory import create_datasource


async def execute_query(state: AgentState) -> AgentState:
    sql = state.get("generated_sql", "")
    configs = state.get("datasource_configs", [])

    if not sql:
        return {**state, "error": "No SQL to execute"}

    if not configs:
        return {**state, "error": "No datasource configs available"}

    errors = []
    for cfg_str in configs:
        try:
            cfg = json.loads(cfg_str) if isinstance(cfg_str, str) else cfg_str
            ds_type = cfg["type"]
            ds_config = cfg["config"]
            connector = create_datasource(ds_type, ds_config)

            await connector.connect()

            # Auto-compute total columns before SQL execution
            if hasattr(connector, "auto_add_total_columns"):
                totals = connector.auto_add_total_columns()
                if totals:
                    # Rewrite SQL to use computed total columns where possible
                    sql = _rewrite_sql_with_totals(sql, totals)

            result = await connector.execute_query(sql)
            await connector.disconnect()

            query_result = {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "elapsed_ms": result.elapsed_ms,
            }
            return {**state, "query_result_json": json.dumps(query_result, ensure_ascii=False)}
        except Exception as e:
            errors.append(f"{cfg.get('type', '?')}: {e}")
            continue

    return {**state, "error": f"SQL execution failed: {'; '.join(errors)}"}


def _rewrite_sql_with_totals(sql: str, totals: dict[str, list[str]]) -> str:
    """Replace manual column summation with computed total columns.

    For example, if totals={"总销量": ["京东销量","天猫销量","拼多多销量"]},
    replace `"京东销量" + "天猫销量" + "拼多多销量"` with `"总销量"`.

    Also handles `SUM("京东销量" + "天猫销量" + "拼多多销量")` → `SUM("总销量")`.
    """
    import re

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
