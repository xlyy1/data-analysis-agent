"""SQL 失败重试 / 空结果 / 出错跳过下游 的测试。"""
import json

import pytest

from app.agent.graph import route_after_execute
from app.agent.nodes.respond import EMPTY_RESULT_MESSAGE, format_response


class TestRouteAfterExecute:
    def test_error_with_budget_retries(self):
        state = {"error": "SQL execution failed: no such column", "sql_retry_count": 1}
        assert route_after_execute(state) == "retry"

    def test_error_without_budget_responds(self):
        state = {"error": "SQL execution failed: no such column", "sql_retry_count": 2}
        assert route_after_execute(state) == "respond"

    def test_empty_result_responds(self):
        state = {"error": "", "empty_result": True}
        assert route_after_execute(state) == "respond"

    def test_normal_result_analyzes(self):
        state = {"error": "", "empty_result": False}
        assert route_after_execute(state) == "analyze"


class TestFormatResponseShortCircuit:
    @pytest.mark.asyncio
    async def test_empty_result_does_not_call_model(self, monkeypatch):
        import app.agent.nodes.respond as respond

        def _boom():
            raise AssertionError("不该取模型")

        monkeypatch.setattr(respond, "get_llm", _boom)
        result = await format_response({"empty_result": True})
        assert result["final_response"] == EMPTY_RESULT_MESSAGE

    @pytest.mark.asyncio
    async def test_error_result_reports_without_model(self, monkeypatch):
        import app.agent.nodes.respond as respond

        def _boom():
            raise AssertionError("不该取模型")

        monkeypatch.setattr(respond, "get_llm", _boom)
        result = await format_response({"error": "connection refused"})
        assert "分析出错" in result["final_response"]
        assert "connection refused" in result["final_response"]


class TestExecuteFlags:
    @pytest.mark.asyncio
    async def test_failed_execution_records_error_and_count(self, monkeypatch):
        import app.agent.nodes.execute as execute

        class _Connector:
            def __init__(self):
                pass

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            async def execute_query(self, sql):
                raise RuntimeError("no such column: region")

        monkeypatch.setattr(execute, "create_datasource", lambda *a, **k: _Connector())
        cfg = json.dumps({"type": "sqlite", "config": {"path": "x.db"}})
        state = {"generated_sql": "SELECT region FROM t", "datasource_configs": [cfg],
                 "sql_retry_count": 0}

        result = await execute.execute_query(state)

        assert result["sql_retry_count"] == 1
        assert "no such column" in result["sql_error"]
        assert result["error"]

    @pytest.mark.asyncio
    async def test_zero_rows_sets_empty_flag(self, monkeypatch):
        import app.agent.nodes.execute as execute

        class _Result:
            columns = ["a"]
            rows = []
            row_count = 0
            elapsed_ms = 1

        class _Connector:
            async def connect(self):
                return None

            async def disconnect(self):
                return None

            async def execute_query(self, sql):
                return _Result()

        monkeypatch.setattr(execute, "create_datasource", lambda *a, **k: _Connector())
        cfg = json.dumps({"type": "sqlite", "config": {"path": "x.db"}})
        state = {"generated_sql": "SELECT a FROM t", "datasource_configs": [cfg],
                 "sql_retry_count": 0}

        result = await execute.execute_query(state)

        assert result["empty_result"] is True
        assert result["error"] == ""
