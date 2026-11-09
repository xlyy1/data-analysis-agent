"""部分成功降级测试：个别数据源失败不应拖垮整次查询。"""
import asyncio
import json

import pytest

from app.agent.nodes import execute as execute_mod


class _Result:
    columns = ["a"]
    rows = [[1]]
    row_count = 1
    elapsed_ms = 1


class _OkConnector:
    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def execute_query(self, sql):
        return _Result()


class _BadConnector:
    async def connect(self):
        raise RuntimeError("connection refused")

    async def disconnect(self):
        return None

    async def execute_query(self, sql):
        return _Result()


def _configs(*names):
    return [json.dumps({"type": name, "config": {}}) for name in names]


@pytest.mark.asyncio
async def test_one_source_failure_still_returns_result(monkeypatch):
    def factory(ds_type, config):
        return _OkConnector() if ds_type == "ok" else _BadConnector()

    monkeypatch.setattr(execute_mod, "create_datasource", factory)

    result = await execute_mod.execute_query({
        "generated_sql": "SELECT 1",
        "datasource_configs": _configs("ok", "bad"),
        "sql_retry_count": 0,
    })

    assert result["error"] == "", "存在可用源时不应判为整体失败"
    assert result["query_result_json"], "应返回可用源的结果"
    status = {item["datasource"]: item["ok"] for item in result["datasource_status"]}
    assert status == {"ok": True, "bad": False}
    assert any("取数失败" in w["message"] for w in result["result_warnings"]), "降级需要明确告警"


@pytest.mark.asyncio
async def test_all_sources_failure_is_error(monkeypatch):
    monkeypatch.setattr(execute_mod, "create_datasource", lambda *a, **k: _BadConnector())

    result = await execute_mod.execute_query({
        "generated_sql": "SELECT 1",
        "datasource_configs": _configs("bad1", "bad2"),
        "sql_retry_count": 0,
    })

    assert result["error"].startswith("SQL execution failed")
    assert result["sql_retry_count"] == 1
    assert all(not item["ok"] for item in result["datasource_status"])


@pytest.mark.asyncio
async def test_all_sources_success_has_no_warning(monkeypatch):
    monkeypatch.setattr(execute_mod, "create_datasource", lambda *a, **k: _OkConnector())

    result = await execute_mod.execute_query({
        "generated_sql": "SELECT 1",
        "datasource_configs": _configs("a", "b"),
        "sql_retry_count": 0,
    })

    assert result["error"] == ""
    assert not any("取数失败" in w["message"] for w in result["result_warnings"])
