"""Sub-agent 调度测试：重试、超时、失败隔离、主路径 + 兜底路径。"""

import asyncio

import pytest

from app.agent.orchestrator import (
    SubAgentError,
    SubTask,
    dispatch,
    looks_failed,
    run_subtask,
)


def ok_state(text: str = "完成") -> dict:
    return {"final_response": text, "error": ""}


def test_looks_failed_rules():
    assert looks_failed({}) is True
    assert looks_failed({"error": "boom"}) is True
    assert looks_failed({"clarification_question": "请补充时间范围"}) is False
    assert looks_failed({"final_response": "结果如下", "error": "warning"}) is False


@pytest.mark.asyncio
async def test_run_subtask_retries_then_succeeds():
    calls = {"n": 0}

    async def flaky(state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("第一次失败")
        return ok_state("第二次成功")

    sub = SubTask("flaky", flaky, max_attempts=2)
    result = await run_subtask(sub, {})
    assert result["final_response"] == "第二次成功"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_run_subtask_raises_after_attempts():
    async def always_fail(state):
        raise RuntimeError("一直失败")

    sub = SubTask("always", always_fail, max_attempts=2)
    with pytest.raises(SubAgentError) as ei:
        await run_subtask(sub, {})
    assert ei.value.attempts == 2
    assert "一直失败" in ei.value.last_error


@pytest.mark.asyncio
async def test_run_subtask_timeout_is_retried():
    async def slow(state):
        await asyncio.sleep(0.2)
        return ok_state()

    sub = SubTask("slow", slow, max_attempts=2, timeout_s=0.05)
    with pytest.raises(SubAgentError) as ei:
        await run_subtask(sub, {})
    assert "timeout" in ei.value.last_error


@pytest.mark.asyncio
async def test_empty_response_counts_as_failure():
    async def empty(state):
        return {"final_response": "", "clarification_question": "", "error": ""}

    sub = SubTask("empty", empty, max_attempts=2)
    with pytest.raises(SubAgentError):
        await run_subtask(sub, {})


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_second_subtask():
    async def primary(state):
        raise RuntimeError("主路径挂了")

    async def fallback(state):
        return ok_state("兜底成功")

    result = await dispatch(
        [
            SubTask("primary", primary, max_attempts=1),
            SubTask("fallback", fallback, max_attempts=1),
        ],
        {"user_input": "x"},
    )

    assert result.state["final_response"] == "兜底成功"
    assert result.notes and "主路径挂了" in result.notes[0]
    assert result.attempts["primary"] == 1
    assert result.ok is True, "兜底成功时整体应判定为成功"


@pytest.mark.asyncio
async def test_dispatch_reports_failure_when_all_fail():
    async def bad(state):
        raise RuntimeError("全挂")

    result = await dispatch(
        [SubTask("a", bad, max_attempts=1), SubTask("b", bad, max_attempts=1)],
        {"user_input": "x"},
    )

    assert result.ok is False
    assert result.failed == ["a", "b"]
    assert len(result.notes) == 2


@pytest.mark.asyncio
async def test_non_critical_failure_does_not_fail_dispatch():
    async def bad(state):
        raise RuntimeError("可选任务失败")

    async def good(state):
        return ok_state("主任务完成")

    result = await dispatch(
        [
            SubTask("optional", bad, max_attempts=1, critical=False),
            SubTask("main", good, max_attempts=1),
        ],
        {"user_input": "x"},
        stop_on_first_success=False,
    )

    assert result.state["final_response"] == "主任务完成"
    assert result.failed == []
    assert result.notes
