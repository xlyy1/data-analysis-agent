"""执行链路追踪测试：事件落库、task_id 复用、异常记录、回放排序。"""


import pytest

from app.observability import trace
from app.observability.replay import list_tasks
from app.core.sqlite import sqlite_connection


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "traces.db"
    monkeypatch.setattr(trace.get_settings(), "trace_db_path", str(path), raising=False)
    trace.init_db(path)
    return path


@pytest.mark.asyncio
async def test_traced_records_success(db):
    @trace.traced("understand_intent")
    async def node(state):
        return {**state, "analysis_type": "trend", "needs_clarification": False}

    result = await node({"user_input": "近三个月销售额趋势"})

    events = trace.load_trace(result["trace_id"], db)
    assert len(events) == 1
    assert events[0]["node"] == "understand_intent"
    assert events[0]["status"] == "ok"
    assert events[0]["duration_ms"] >= 0
    assert events[0]["fields"]["analysis_type"] == "trend"


@pytest.mark.asyncio
async def test_trace_id_shared_across_nodes(db):
    @trace.traced("first")
    async def first(state):
        return {**state}

    @trace.traced("second")
    async def second(state):
        return {**state}

    s = await first({})
    s = await second(s)

    events = trace.load_trace(s["trace_id"], db)
    assert [e["node"] for e in events] == ["first", "second"]
    assert [e["seq"] for e in events] == [1, 2]


@pytest.mark.asyncio
async def test_traced_records_error_and_reraises(db):
    @trace.traced("generate_query")
    async def broken(state):
        raise ValueError("LLM 返回的不是 JSON")

    with pytest.raises(ValueError):
        await broken({})

    rows = list_tasks(10, db)
    assert len(rows) == 1
    events = trace.load_trace(rows[0]["task_id"], db)
    assert events[0]["status"] == "error"
    assert "LLM 返回的不是 JSON" in events[0]["error"]


@pytest.mark.asyncio
async def test_trace_disabled_writes_nothing(db, monkeypatch):
    monkeypatch.setattr(trace.get_settings(), "trace_enabled", False, raising=False)

    @trace.traced("understand_intent")
    async def node(state):
        return {**state}

    await node({"user_input": "x"})
    with sqlite_connection(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
    assert count == 0


def test_summarize_renders_timeline(db):
    trace.record("t1", "understand_intent", "ok", 0.0, 12.0, {"analysis_type": "trend"}, db_path=db)
    trace.record("t1", "generate_query", "ok", 0.1, 830.0, {"generated_sql": "SELECT 1"}, db_path=db)

    text = trace.summarize(trace.load_trace("t1", db))
    assert "understand_intent" in text
    assert "generate_query" in text
    assert "2 events" in text


def test_extract_fields_truncates_long_values():
    fields = trace.extract_fields(
        "format_response", {"final_response": "长" * 1000, "trace_id": "x"}
    )
    assert len(fields["final_response"]) < 520
    assert "1000 chars" in fields["final_response"]
