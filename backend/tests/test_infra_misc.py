"""零散但重要的模块测试：Mock LLM、限流器、LLM 超时包装、SQL 校验接口、路径解析。"""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings, get_settings
from app.database import resolve_database_url, sync_database_url
from app.llm.base import BaseLLM, LLMTimeoutError, TimedLLM
from app.llm.factory import get_llm
from app.llm.mock import MockLLM, looks_deterministic
from app.services.rate_limit import KeyedLimiters, SlidingWindowLimiter


class TestMockLLM:
    async def test_intent_branch_detects_vague_question(self):
        llm = MockLLM()
        raw = await llm.chat(
            [
                {"role": "system", "content": "你是一个数据分析意图识别器。请返回 JSON"},
                {"role": "user", "content": "帮我看看销售情况"},
            ]
        )
        assert '"needs_clarification": true' in raw

    async def test_intent_branch_accepts_concrete_question(self):
        llm = MockLLM()
        raw = await llm.chat(
            [
                {"role": "system", "content": "你是一个数据分析意图识别器。"},
                {"role": "user", "content": "各城市的销售额排名"},
            ]
        )
        assert '"needs_clarification": false' in raw
        assert '"analysis_type": "comparison"' in raw

    async def test_sql_branch_uses_schema(self):
        import json

        llm = MockLLM()
        schema = (
            '{"tables": [{"name": "订单明细", "columns": ['
            '{"name": "城市", "dtype": "TEXT", "sample_values": ["杭州"]},'
            '{"name": "销售额", "dtype": "REAL"}]}]}'
        )
        raw = await llm.chat(
            [
                {"role": "system", "content": f'SQL 生成器。schema:\n{schema}\n返回 {{"sql": "SELECT ..."}}'},
                {"role": "user", "content": "各城市的销售额"},
            ]
        )
        payload = json.loads(raw)
        sql = payload["sql"]
        assert "订单明细" in sql
        assert '"城市"' in sql, "问句里点名的维度应当被优先选中"
        assert '"销售额"' in sql, "问句里点名的指标应当被优先选中"
        assert "GROUP BY" in sql.upper()

    async def test_sql_branch_without_schema_is_safe(self):
        llm = MockLLM()
        raw = await llm.chat(
            [
                {"role": "system", "content": '返回 {"sql": "SELECT ..."}'},
                {"role": "user", "content": "随便问问"},
            ]
        )
        assert "SELECT 1" in raw

    async def test_analyze_and_diagnose_branches(self):
        llm = MockLLM()
        analyze = await llm.chat(
            [{"role": "system", "content": '请返回 JSON {"summary": "分析摘要"}'}]
        )
        assert '"summary"' in analyze
        diagnose = await llm.chat(
            [{"role": "system", "content": '请返回 JSON {"causes": ['}]
        )
        assert '"causes"' in diagnose

    async def test_reply_branch_is_plain_text(self):
        llm = MockLLM()
        text = await llm.chat([{"role": "system", "content": "请生成最终回复"}])
        assert "SELECT" not in text
        assert llm.model_name == "mock/deterministic"

    def test_looks_deterministic_probe(self):
        assert looks_deterministic('返回 {"sql": "x"}') is True
        assert looks_deterministic("随便一句话") is False

    def test_factory_returns_mock_for_mock_provider(self):
        assert isinstance(get_llm("mock"), MockLLM)


class _SlowLLM(BaseLLM):
    @property
    def model_name(self) -> str:
        return "slow/test"

    async def chat(self, messages, **kwargs):
        await asyncio.sleep(5)
        return "late"

    async def chat_stream(self, messages, **kwargs):
        yield "late"


class TestTimedLLM:
    async def test_timeout_is_converted_to_llm_timeout_error(self):
        wrapped = TimedLLM(_SlowLLM(), timeout_seconds=0.05)
        with pytest.raises(LLMTimeoutError):
            await wrapped.chat([{"role": "user", "content": "hi"}])

    async def test_fast_response_passes_through(self):
        wrapped = TimedLLM(MockLLM(), timeout_seconds=5)
        assert wrapped.model_name == "mock/deterministic"
        out = await wrapped.chat([{"role": "system", "content": "请生成最终回复"}])
        assert out

    def test_timeout_has_floor(self):
        assert TimedLLM(MockLLM(), timeout_seconds=0).model_name == "mock/deterministic"


class TestRateLimiter:
    def test_allows_up_to_limit_then_blocks(self):
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
        assert [limiter.allow("k") for _ in range(3)] == [True, True, True]
        assert limiter.allow("k") is False

    def test_separate_keys_are_independent(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        assert limiter.allow("a") is True
        assert limiter.allow("b") is True
        assert limiter.allow("a") is False

    def test_reset_clears_bucket(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        assert limiter.allow("k") is True
        limiter.reset("k")
        assert limiter.allow("k") is True
        limiter.reset()
        assert limiter.retry_after("k") == 0.0

    def test_keyed_limiters_rebuild_on_limit_change(self):
        registry = KeyedLimiters()
        first = registry.get("x", 5, 60)
        second = registry.get("x", 10, 60)
        assert first is not second
        assert second.limit == 10
        registry.reset()


class TestSqlValidateEndpoint:
    async def test_blocks_write(self, client):
        response = await client.post("/api/sql/validate", json={"sql": "DROP TABLE t"})
        assert response.status_code == 200
        body = response.json()
        assert body["allowed"] is False
        assert body["code"] == "sql_write_forbidden"
        assert body["policy"]["write_allowed"] is False

    async def test_allows_readonly_and_reports_limit(self, client):
        body = (
            await client.post("/api/sql/validate", json={"sql": "SELECT 1"})
        ).json()
        assert body["allowed"] is True
        assert body["applied_limit"] == get_settings().sql_default_limit
        assert body["normalized_sql"].startswith("SELECT 1")

    async def test_allow_write_flag_cannot_override_policy(self, client):
        body = (
            await client.post(
                "/api/sql/validate", json={"sql": "DELETE FROM t", "allow_write": True}
            )
        ).json()
        assert body["allowed"] is False


class TestPathResolution:
    def test_blank_url_falls_back_to_repo_data_dir(self, monkeypatch):
        get_settings().database_url = ""
        url = resolve_database_url()
        assert url.startswith("sqlite+aiosqlite:///")
        assert url.endswith("agent.db")

    def test_relative_sqlite_gets_async_driver(self, monkeypatch):
        get_settings().database_url = "sqlite:///./data/x.db"
        url = resolve_database_url()
        assert url.startswith("sqlite+aiosqlite:///")
        assert sync_database_url(url).startswith("sqlite:///")

    def test_postgres_url_gets_asyncpg(self):
        get_settings().database_url = "postgresql://u:p@h:5432/db"
        try:
            url = resolve_database_url()
        finally:
            get_settings().database_url = ""
        assert url.startswith("postgresql+asyncpg://")

    def test_settings_cors_origins_split(self):
        settings = Settings(cors_origins="https://a.com, https://b.com")
        assert settings.cors_origin_list == ["https://a.com", "https://b.com"]

    def test_settings_cors_wildcard_default(self):
        assert Settings(cors_origins="").cors_origin_list == ["*"]
