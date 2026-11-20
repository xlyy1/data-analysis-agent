"""历史对话的上下文压缩（context compaction）。

多轮对话历史会线性膨胀，超出预算后既贵又容易让模型丢掉最新意图。这里的策略是
「摘要 + 近窗」：把较早的若干轮压成一条摘要消息，保留最近 N 条原文。

设计取舍：
- token 用启发式估算（中文按字、其他按 4 字符/token），不引第三方 tokenizer；
- 摘要优先走 LLM，LLM 不可用或超时则退化为抽取式摘要，保证压缩永远能完成；
- 压缩结果与统计（前后 token、被压缩条数）会写入执行追踪，便于回放时看到「这次为什么变便宜了」。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)

CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F), (0xFF00, 0xFFEF))


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文 1 字≈1 token，其余 4 字符≈1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def messages_tokens(messages: Sequence[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(str(m.get("content", ""))) + 4  # 角色与分隔符开销
    return total


@dataclass
class CompactionResult:
    messages: list[dict[str, Any]]
    compacted: bool = False
    dropped: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    used_llm: bool = False
    summary: str = ""
    notes: list[str] = field(default_factory=list)

    def stats(self) -> dict[str, Any]:
        return {
            "compacted": self.compacted,
            "dropped": self.dropped,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "used_llm": self.used_llm,
        }


SUMMARIZE_PROMPT = """把下面这段较早的对话压缩成结构化摘要，供后续追问时参考。

输出格式（严格按下面 5 行，没有的写「无」）：
口径：<时间范围、统计粒度、指标口径，逐字保留原表述>
维度：<按什么拆解>
结论：<已得出的数字结论，保留原始数字与单位>
待办：<尚未确认的事项>
其他：<其他必须记住的约束，例如数据源表名>

硬性要求：
- 数字、单位、表名、字段名、门店名必须原样保留，不得改写、缩写或四舍五入；
- 不要编造未出现的信息，不要输出寒暄；
- 总长度不超过 300 字。"""


# 抽取式兜底时优先保留的线索词：口径、时间、对比、结论、待办、异常
_KEY_CUES = (
    "口径", "时间", "范围", "同比", "环比", "对比", "结论", "合计", "总计",
    "待办", "确认", "缺失", "异常", "下降", "增长", "字段", "维度",
    "数据源", "表", "库", "指标", "筛选", "分组",
)


def _split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for chunk in str(text).replace("\n", "。").split("。"):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return out


def _score_sentence(sentence: str) -> int:
    """含数字与线索词的句子更可能承载事实，优先保留。"""
    score = sum(2 for ch in sentence if ch.isdigit())
    score += sum(1 for cue in _KEY_CUES if cue in sentence)
    return score


# 寒暄与确认类句子：没有事实，不该占摘要预算
_FILLER_PATTERNS = (
    "好的", "好，", "明白了", "收到", "没问题", "了解", "已记录", "已按",
    "谢谢", "请稍等", "稍等", "可以的", "当然", "我理解", "嗯",
)


def _is_filler(sentence: str) -> bool:
    """判断一句话是不是纯寒暄/确认。

    只看开头会误杀「好的，已记录：数据源 warehouse.db 的 sales 表」这种
    「寒暄 + 事实」混写句，所以这里按「去掉寒暄后还剩多少内容」判断：
    - 短句（≤12 字）几乎都是寒暄；
    - 以寒暄词开头但整体很短（≤24 字）也算寒暄；
    - 更长的句子即使开头是寒暄，也认为后面带了信息，保留。
    """
    if _score_sentence(sentence) > 0:
        return False
    s = sentence.strip()
    if len(s) <= 12:
        return True
    if len(s) <= 24 and any(s.startswith(p) for p in _FILLER_PATTERNS):
        return True
    return False


def extractive_summary(messages: Sequence[dict[str, Any]], max_chars: int = 800) -> str:
    """不依赖 LLM 的退化摘要：按「数字 + 线索词」挑句子。

    演进过程：
    1. 旧实现每轮截前 60 字 —— 实测 10 个关键事实只剩 2 个；
    2. 改为打分抽取 + 每轮首句保底 —— 10/10，但首句常是寒暄，浪费预算；
    3. 现在改成「每轮保该轮最高分句，寒暄句直接丢弃」：既保证每轮有代表，
       也不让「好的，我明白了」这种句子占用。

    若某一轮全是寒暄，则允许整轮被丢弃（它本来就没有信息）。
    """
    picked: list[tuple[int, int, int, str]] = []  # (score, 原顺序, 句序, 文本)
    for idx, m in enumerate(messages):
        role = str(m.get("role", "user"))
        best: tuple[int, str] | None = None
        for s_idx, sentence in enumerate(_split_sentences(m.get("content", ""))):
            if len(sentence) < 4 or _is_filler(sentence):
                continue
            score = _score_sentence(sentence)
            if best is None or score > best[0]:
                best = (score, sentence)
            if score >= 2:
                picked.append((score, idx, s_idx, f"{role}: {sentence[:100]}"))
        # 该轮没有任何高分句时，用该轮最高分句兜底（避免整轮无代表）
        if best is not None and best[0] < 2:
            picked.append((best[0], idx, -1, f"{role}: {best[1][:80]}"))

    picked.sort(key=lambda x: (-x[0], x[1], x[2]))
    out: list[str] = []
    used = 0
    seen: set[str] = set()
    for _, _, _, text in picked:
        # 长会话里同一句会被反复追问，重复句只保留一次，省下的预算留给别的事实
        key = text.split(": ", 1)[-1][:30]
        if key in seen:
            continue
        if used + len(text) > max_chars:
            continue
        seen.add(key)
        out.append(text)
        used += len(text) + 1
    return "；".join(out)[:max_chars]


async def compact_history(
    messages: Sequence[dict[str, Any]],
    max_tokens: int = 1500,
    keep_recent: int = 6,
    summarize: Callable[[str], Awaitable[str]] | None = None,
) -> CompactionResult:
    """把较早的对话压成摘要，保留最近 keep_recent 条原文。

    summarize: 传入一个 async 函数（入参为待压缩对话文本，返回摘要），
    为 None 或抛异常时退化为抽取式摘要。
    """
    msgs = [dict(m) for m in messages]
    before = messages_tokens(msgs)
    if before <= max_tokens or len(msgs) <= keep_recent:
        return CompactionResult(messages=msgs, tokens_before=before, tokens_after=before)

    older = msgs[:-keep_recent]
    recent = msgs[-keep_recent:]

    # 头部原文保底：口径、表名、待办这类信息通常最早出现，摘要改写容易丢细节。
    # 头部预算占总预算的 1/4，剩下的中间段才交给 LLM 摘要。
    head_budget = max_tokens // 4
    head: list[dict[str, Any]] = []
    used = 0
    for m in older:
        cost = estimate_tokens(str(m.get("content", ""))) + 4
        if used + cost > head_budget:
            break
        head.append(m)
        used += cost
    middle = older[len(head):]
    transcript = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in middle)

    summary = ""
    used_llm = False
    notes: list[str] = []
    if summarize is not None and middle:
        try:
            summary = (await summarize(transcript)).strip()
            used_llm = bool(summary)
        except Exception as exc:  # noqa: BLE001 - 压缩失败必须能降级
            notes.append(f"llm summarize failed: {type(exc).__name__}")
            logger.warning("context compaction fell back: %s", exc)

    if summary:
        lead = {
            "role": "system",
            "content": f"中间 {len(middle)} 条对话的摘要（早期原文与最近对话已保留）：{summary}",
        }
        result_msgs = [*head, lead, *recent]
    else:
        # 兜底：不做「假摘要」。抽取式在真实长会话上实测只有 4% 的事实留存
        # （填充轮的数字比事实更多，打分会被填充句吃掉），所以宁可按预算多留原文。
        wide_budget = max_tokens // 2
        wide: list[dict[str, Any]] = list(older)
        used = 0
        trimmed: list[dict[str, Any]] = []
        for m in wide:
            cost = estimate_tokens(str(m.get("content", ""))) + 4
            if used + cost > wide_budget:
                break
            trimmed.append(m)
            used += cost
        omitted = len(older) - len(trimmed)
        marker = {
            "role": "system",
            "content": f"（中间 {omitted} 条对话超出上下文预算被省略；以上为早期原文，以下为最近对话）",
        }
        result_msgs = [*trimmed, marker, *recent] if trimmed else [marker, *recent]
        notes.append("fallback: head+tail")

    after = messages_tokens(result_msgs)
    return CompactionResult(
        messages=result_msgs,
        compacted=True,
        dropped=len(older) - len(head),
        tokens_before=before,
        tokens_after=after,
        used_llm=used_llm,
        summary=summary,
        notes=notes,
    )


def make_llm_summarizer(llm: Any) -> Callable[[str], Awaitable[str]]:
    """把项目内的 LLM 客户端包装成 compact_history 需要的 summarize 函数。"""

    async def _summarize(transcript: str) -> str:
        resp = await llm.chat(
            [
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {"role": "user", "content": transcript},
            ]
        )
        return (resp or "").strip()

    return _summarize
