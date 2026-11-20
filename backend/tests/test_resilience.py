"""超时与并行取数的测试。"""
import asyncio
import json
import time

import pytest

from app.agent.nodes import execute as execute_mod
from app.services.resilience import StepTimeout, run_with_retry


class TestRunWithRetry:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        async def ok():
            return "done"

        value, attempts = await run_with_retry(ok, timeout=1, retries=1)
        assert (value, attempts) == ("done", 1)

    @pytest.mark.asyncio
    async def test_timeout_then_success(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                await asyncio.sleep(0.3)
            return "ok"

        value, attempts = await run_with_retry(flaky, timeout=0.1, retries=1)
        assert value == "ok"
        assert attempts == 2, "超时后应重试一次"

    @pytest.mark.asyncio
    async def test_exhausted_retries_raise(self):
        async def slow():
            await asyncio.sleep(0.3)
            return "never"

        with pytest.raises(StepTimeout):
            await run_with_retry(slow, timeout=0.05, retries=1)


class _Result:
    columns = ["a"]
    rows = [[1]]
    row_count = 1
    elapsed_ms = 1


class _Connector:
    def __init__(self, delay=0.0, fail_times=0):
        self.delay = delay
        self.fail_times = fail_times
        self.calls = 0

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def execute_query(self, sql):
        self.calls += 1
        if self.calls <= self.fail_times:
            await asyncio.sleep(10)   # 触发超时
        if self.delay:
            await asyncio.sleep(self.delay)
        return _Result()


def _patch(monkeypatch, factory):
    monkeypatch.setattr(execute_mod, "create_datasource", factory)


@pytest.mark.asyncio
async def test_sources_run_in_parallel(monkeypatch):
    created = []

    def factory(ds_type, config):
        connector = _Connector(delay=0.2)
        created.append(connector)
        return connector

    _patch(monkeypatch, factory)
    configs = [json.dumps({"type": "a", "config": {}}), json.dumps({"type": "b", "config": {}})]

    start = time.perf_counter()
    result = await execute_mod.execute_query({"generated_sql": "SELECT 1", "datasource_configs": configs})
    elapsed = time.perf_counter() - start

    assert result["error"] == ""
    assert elapsed < 0.35, f"两个 0.2s 的源应并行完成，实际 {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_source_timeout_is_retried(monkeypatch):
    monkeypatch.setenv("QUERY_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setenv("QUERY_RETRIES", "1")
    from app.config import get_settings

    get_settings.cache_clear()

    connectors = []
    state = {"calls": 0}

    class Shared(_Connector):
        async def execute_query(self, sql):
            state["calls"] += 1
            if state["calls"] == 1:
                await asyncio.sleep(10)   # 只有第一次超时
            return _Result()

    def factory(ds_type, config):
        connector = Shared()
        connectors.append(connector)
        return connector

    _patch(monkeypatch, factory)
    result = await execute_mod.execute_query({
        "generated_sql": "SELECT 1",
        "datasource_configs": [json.dumps({"type": "a", "config": {}})],
    })

    get_settings.cache_clear()
    assert result["error"] == "", f"重试后应成功: {result.get('error')}"
    assert len(connectors) == 2, "超时后应新建连接重试"
