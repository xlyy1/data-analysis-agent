"""Agent 图端到端测试（离线）。

用 `LLM_PROVIDER=mock` 跑完整 LangGraph：理解 → 生成 SQL → 执行 → 分析 → 诊断 →
可视化 → 回答。验证的是**机制**，不是模型能力。
"""

from __future__ import annotations

import json

import pytest

from app.agent.graph import agent_app
from app.agent.nodes.execute import execute_query
from app.datasource.factory import create_datasource
from app.services.schema import describe_schema
from app.core.sqlite import sqlite_connection

pytestmark = pytest.mark.asyncio


@pytest.fixture()
async def dataset(tmp_path):
    path = tmp_path / "shop.db"
    with sqlite_connection(path) as conn:
        conn.execute('CREATE TABLE orders (city TEXT, channel TEXT, amount REAL, profit REAL)')
        conn.executemany(
            "INSERT INTO orders VALUES (?,?,?,?)",
            [
                ("杭州", "线上", 1000.0, 300.0),
                ("杭州", "批发", 800.0, -50.0),
                ("苏州", "线上", 600.0, 180.0),
                ("宁波", "线下", 400.0, 90.0),
            ],
        )
        conn.execute('CREATE TABLE regions (city TEXT PRIMARY KEY, manager TEXT)')
        conn.executemany("INSERT INTO regions VALUES (?,?)", [("杭州", "张三"), ("苏州", "李四")])
        conn.commit()

    connector = create_datasource("sqlite", {"db_path": str(path)})
    await connector.connect()
    try:
        schema = await describe_schema(connector, use_cache=False)
    finally:
        await connector.disconnect()
    return {
        "schema": json.dumps(schema, ensure_ascii=False),
        "config": json.dumps({"type": "sqlite", "config": {"db_path": str(path)}}),
    }


def initial_state(dataset, question: str, allow_write: bool = False) -> dict:
    return {
        "messages": [],
        "trace_id": "",
        "user_input": question,
        "datasource_ids": ["ds"],
        "datasource_schemas": [dataset["schema"]],
        "datasource_configs": [dataset["config"]],
        "intent": "",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
        "generated_sql": "",
        "sql_explanation": "",
        "sql_needs_confirmation": False,
        "sql_retry_count": 0,
        "sql_error": "",
        "empty_result": False,
        "result_warnings": [],
        "datasource_status": [],
        "query_result_json": "{}",
        "analysis_type": "summary",
        "analysis_summary": "",
        "diagnosis_causes": [],
        "diagnosis_evidence": [],
        "diagnosis_suggestions": [],
        "chart_config_json": "{}",
        "final_response": "",
        "error": "",
        "allow_write": allow_write,
    }


class TestFullGraph:
    async def test_concrete_question_produces_sql_rows_chart_answer(self, dataset):
        state = await agent_app.ainvoke(initial_state(dataset, "各城市的销售额排名"))

        assert state["needs_clarification"] is False
        assert state["generated_sql"].upper().startswith("SELECT")
        assert not state["error"], state.get("sql_error")
        assert state["final_response"]

        result = json.loads(state["query_result_json"])
        assert result["columns"]
        assert len(result["rows"]) >= 1
        # 明细里只有 4 行，分组后至少 1 行
        assert result["row_count"] >= 1

        chart = json.loads(state["chart_config_json"])
        assert chart["echarts_option"]["series"]

    async def test_vague_question_clarifies_and_skips_execution(self, dataset):
        state = await agent_app.ainvoke(initial_state(dataset, "帮我看看销售情况"))

        assert state["needs_clarification"] is True
        assert state["clarification_question"]
        assert state["clarification_options"]
        assert state["generated_sql"] == "", "澄清时不应生成/执行 SQL"

    async def test_diagnostic_question_runs_diagnose_node(self, dataset):
        state = await agent_app.ainvoke(initial_state(dataset, "哪个渠道的利润最低，为什么"))
        assert state["diagnosis_causes"] or state["analysis_summary"]
        assert state["chart_config_json"] not in ("", "{}")

    async def test_sql_carries_limit_after_guard(self, dataset):
        state = await agent_app.ainvoke(initial_state(dataset, "总销售额是多少"))
        if state["generated_sql"]:
            assert "LIMIT" in state["generated_sql"].upper()


class TestExecutorGuard:
    async def test_write_sql_blocked_before_touching_database(self, dataset):
        state = initial_state(dataset, "删掉订单")
        state["generated_sql"] = 'DELETE FROM "orders"'
        result = await execute_query(state)
        assert result["error"]
        assert "只读" in result["error"]
        assert result["sql_retry_count"] == 1
        # 没有连接、没有查询结果
        assert result["query_result_json"] == "{}"

    async def test_multi_statement_blocked(self, dataset):
        state = initial_state(dataset, "注入")
        state["generated_sql"] = 'SELECT 1; DROP TABLE "orders"'
        result = await execute_query(state)
        assert "单条 SQL" in result["error"] or "只允许" in result["error"]

    async def test_allow_write_flag_is_still_read_only_by_default(self, dataset):
        state = initial_state(dataset, "改数据", allow_write=True)
        state["generated_sql"] = 'UPDATE "orders" SET "amount" = 0'
        result = await execute_query(state)
        # SQL_ALLOW_WRITE_FOR_ADMIN 默认 false，所以即便 allow_write 也拒绝
        assert result["error"]

    async def test_normal_select_is_limited_and_executed(self, dataset):
        state = initial_state(dataset, "明细")
        state["generated_sql"] = 'SELECT "city", "amount" FROM "orders"'
        result = await execute_query(state)
        assert result["error"] == ""
        payload = json.loads(result["query_result_json"])
        assert payload["row_count"] == 4
        assert "LIMIT" in payload["executed_sql"].upper()

    async def test_result_is_truncated_with_warning(self, dataset, monkeypatch):
        from app.agent.nodes import execute as execute_module
        from app.config import get_settings

        settings = get_settings()
        # 按"单元格上限"折算：2 列 × 上限 3 → 最多 1 行
        monkeypatch.setattr(settings, "sql_max_result_cells", 3, raising=False)

        state = initial_state(dataset, "明细")
        state["generated_sql"] = 'SELECT "city", "amount" FROM "orders"'
        result = await execute_module.execute_query(state)

        payload = json.loads(result["query_result_json"])
        assert payload["row_count"] == 1
        assert payload["total_row_count"] == 4
        assert any(w.get("column") == "__truncated__" for w in result["result_warnings"])
