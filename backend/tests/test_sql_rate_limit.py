"""SQL 级限流测试。

背景：P2 汇报里写了"SQL 只读 / 限流 / 超时 / 行数上限"，但 `sql_rate_limit_per_minute`
只停留在配置项、没有任何代码读取它 —— 真正接线的只有登录限流。这里补上行为并钉住。
"""

from __future__ import annotations

import json

import pytest

from app.agent.graph import route_after_execute
from app.agent.nodes import execute as execute_mod
from app.agent.nodes.respond import format_response
from app.config import get_settings
from app.services.rate_limit import limiters


class _Result:
    columns = ["a"]
    rows = [[1]]
    row_count = 1
    elapsed_ms = 1


class _Connector:
    def __init__(self) -> None:
        self.calls = 0

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def execute_query(self, sql):
        self.calls += 1
        return _Result()


def state_for(user_id: str) -> dict:
    return {
        "generated_sql": "SELECT a FROM t",
        "datasource_configs": [json.dumps({"type": "sqlite", "config": {}})],
        "sql_retry_count": 0,
        "user_id": user_id,
        "allow_write": False,
    }


@pytest.fixture(autouse=True)
def _reset_limiters(monkeypatch):
    """每个用例独立计数；默认上限调到 2 便于快速触顶。"""
    limiters.reset()
    monkeypatch.setattr(get_settings(), "sql_rate_limit_per_minute", 2, raising=False)
    yield
    limiters.reset()


@pytest.fixture()
def connector(monkeypatch):
    instance = _Connector()
    monkeypatch.setattr(execute_mod, "create_datasource", lambda *a, **k: instance)
    return instance


class TestSqlRateLimit:
    async def test_within_limit_executes(self, connector):
        first = await execute_mod.execute_query(state_for("u1"))
        second = await execute_mod.execute_query(state_for("u1"))
        assert first["error"] == ""
        assert second["error"] == ""
        assert connector.calls >= 2

    async def test_over_limit_blocks_before_touching_datasource(self, connector):
        await execute_mod.execute_query(state_for("u2"))
        await execute_mod.execute_query(state_for("u2"))
        calls_before = connector.calls

        blocked = await execute_mod.execute_query(state_for("u2"))

        assert blocked["error"] == execute_mod.RATE_LIMIT_MESSAGE
        assert blocked["error_non_retryable"] is True
        assert connector.calls == calls_before, "被限流时不应真的连库执行"
        # 限流不计入 SQL 重试预算（否则会反复重写 SQL）
        assert blocked["sql_retry_count"] == 0

    async def test_buckets_are_per_user(self, connector):
        await execute_mod.execute_query(state_for("alice"))
        await execute_mod.execute_query(state_for("alice"))
        # alice 已到上限，bob 不受影响
        alice = await execute_mod.execute_query(state_for("alice"))
        bob = await execute_mod.execute_query(state_for("bob"))
        assert alice["error_non_retryable"] is True
        assert bob["error"] == ""

    async def test_anonymous_falls_back_to_single_bucket(self, connector):
        anonymous = {**state_for(""), "user_id": ""}
        await execute_mod.execute_query(anonymous)
        await execute_mod.execute_query(anonymous)
        blocked = await execute_mod.execute_query(anonymous)
        assert blocked["error_non_retryable"] is True

    async def test_rejected_sql_does_not_consume_quota(self, connector):
        """安全闸拦下的 SQL 不占限流配额（否则越权尝试会把正常用户挤掉）。"""
        bad = {**state_for("u3"), "generated_sql": 'DROP TABLE "t"'}
        for _ in range(5):
            result = await execute_mod.execute_query(bad)
            assert result["error"]
            assert not result.get("error_non_retryable")

        ok = await execute_mod.execute_query(state_for("u3"))
        assert ok["error"] == ""
        assert connector.calls == 1


class TestGraphAndResponse:
    def test_non_retryable_error_goes_straight_to_respond(self):
        state = {"error": execute_mod.RATE_LIMIT_MESSAGE, "error_non_retryable": True, "sql_retry_count": 0}
        assert route_after_execute(state) == "respond"

    def test_normal_error_still_retries(self):
        state = {"error": "no such column", "sql_retry_count": 0}
        assert route_after_execute(state) == "retry"

    async def test_rate_limit_message_is_shown_without_error_prefix(self):
        result = await format_response(
            {"error": execute_mod.RATE_LIMIT_MESSAGE, "error_non_retryable": True}
        )
        assert result["final_response"] == execute_mod.RATE_LIMIT_MESSAGE
        assert "分析出错" not in result["final_response"]

    async def test_other_errors_keep_the_prefix(self):
        result = await format_response({"error": "connection refused"})
        assert "分析出错" in result["final_response"]
