"""上下文压缩测试：阈值、近窗保留、LLM 退化、统计口径。"""

import pytest

from app.agent.context import (
    compact_history,
    estimate_tokens,
    extractive_summary,
    make_llm_summarizer,
    messages_tokens,
)


def _dialog(turns: int, size: int = 120) -> list[dict]:
    msgs = []
    for i in range(turns):
        msgs.append({"role": "user", "content": f"第{i}个问题" + "经" * size})
        msgs.append({"role": "assistant", "content": f"第{i}个回答" + "营" * size})
    return msgs


def test_estimate_tokens_prefers_cjk():
    assert estimate_tokens("销售额") == 3
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 0


def test_messages_tokens_counts_role_overhead():
    msgs = [{"role": "user", "content": "你好"}]
    assert messages_tokens(msgs) == 6  # 2 token 内容 + 4 开销


@pytest.mark.asyncio
async def test_short_history_is_untouched():
    msgs = _dialog(1)
    result = await compact_history(msgs, max_tokens=10_000, keep_recent=6)
    assert result.compacted is False
    assert result.messages == msgs
    assert result.tokens_before == result.tokens_after


@pytest.mark.asyncio
async def test_long_history_compacts_and_keeps_recent():
    msgs = _dialog(10, size=200)
    called = {"n": 0}

    async def fake_summarize(transcript: str) -> str:
        called["n"] += 1
        return "用户在追问各门店销售趋势，口径为最近三个月。"

    result = await compact_history(msgs, max_tokens=200, keep_recent=4, summarize=fake_summarize)

    assert result.compacted is True
    assert result.used_llm is True
    assert called["n"] == 1
    # 新的分层策略：头部原文 + 中间摘要 + 尾部近窗
    assert result.messages[-4:] == msgs[-4:]
    summaries = [m for m in result.messages if m["role"] == "system" and "的摘要" in m["content"]]
    assert summaries, "缺少中间段摘要消息"
    assert "用户在追问各门店销售趋势" in summaries[0]["content"]
    assert result.tokens_after < result.tokens_before


@pytest.mark.asyncio
async def test_summarizer_failure_falls_back():
    msgs = _dialog(8, size=200)

    async def boom(transcript: str) -> str:
        raise RuntimeError("llm timeout")

    result = await compact_history(msgs, max_tokens=200, keep_recent=4, summarize=boom)

    assert result.compacted is True
    assert result.used_llm is False
    assert any("llm summarize failed" in n for n in result.notes)
    assert any("fallback: head+tail" in n for n in result.notes)
    # 兜底不再编摘要，而是保留原文并显式标注省略了多少条
    markers = [m for m in result.messages if m["role"] == "system" and "被省略" in m["content"]]
    assert markers, "兜底必须留一条省略标记"
    assert result.messages[-4:] == msgs[-4:]


@pytest.mark.asyncio
async def test_stats_are_reported():
    msgs = _dialog(6, size=100)
    result = await compact_history(msgs, max_tokens=100, keep_recent=2)
    stats = result.stats()
    assert stats["compacted"] is True
    assert stats["dropped"] == len(msgs) - 2
    assert stats["tokens_before"] > stats["tokens_after"]


def test_extractive_summary_truncates():
    text = extractive_summary([{"role": "user", "content": "长" * 300}], max_chars=60)
    assert len(text) <= 60


@pytest.mark.asyncio
async def test_make_llm_summarizer_calls_chat():
    class FakeLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, messages):
            self.calls.append(messages)
            return "摘要内容"

    llm = FakeLLM()
    summarize = make_llm_summarizer(llm)
    assert await summarize("user: 你好") == "摘要内容"
    assert llm.calls and llm.calls[0][0]["role"] == "system"

FACTS = [
    "A店 周均 12.4 万",
    "B店 最近一周 6.1 万，环比 -22%",
    "C店 数据缺失两周",
    "口径 最近三个月按周拆解",
    "对比 去年同期",
    "维度 按门店 + 按周",
    "异常 B 店旁边新开竞品门店",
    "结论 整体环比 -3%",
    "待办 确认 C 店是否关店",
    "数据源 warehouse.db 的 sales 表",
]


def _long_dialog_with_facts():
    """事实只埋在前 10 轮，后面用填充轮次把它们挤出近窗。"""
    msgs = []
    for f in FACTS:
        msgs.append({"role": "user", "content": f"补充一项：{f}，后面分析都要带上。"})
        msgs.append({"role": "assistant", "content": f"已记录：{f}。"})
    for _ in range(70):
        msgs.append({"role": "user", "content": "再帮我把上周的情况按同样方式拆一遍，看看走势有没有变化。"})
        msgs.append({"role": "assistant", "content": "已按同样口径拆解上周数据：A 店持平，B 店下滑，C 店缺数据。"})
    return msgs


@pytest.mark.asyncio
async def test_fallback_retains_key_facts():
    """抽取式兜底必须保住事实：旧实现只留首 60 字，10 个事实只剩 2 个。"""
    msgs = _long_dialog_with_facts()
    result = await compact_history(msgs, max_tokens=4000, keep_recent=8, summarize=None)

    text = "\n".join(m["content"] for m in result.messages)
    hits = [f for f in FACTS if f in text]
    assert result.compacted is True
    assert len(hits) >= 9, f"关键事实只保住 {len(hits)}/10：{hits}"


def test_summary_prompt_is_structured():
    """摘要 prompt 必须要求结构化字段，否则 LLM 会把口径/维度改写成叙述句。"""
    from app.agent.context import SUMMARIZE_PROMPT

    for field in ("口径", "维度", "结论", "待办", "其他"):
        assert f"{field}：" in SUMMARIZE_PROMPT
    assert "原样保留" in SUMMARIZE_PROMPT
