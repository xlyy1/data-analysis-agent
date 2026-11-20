"""上下文压缩的端到端评测：压缩后还能不能答对依赖早期事实的问题。

与 context_retention_eval.py 的区别：
- 那个测「事实字面还在不在」（代理指标）；
- 这个测「下游任务还做不做得对」（业务指标）：
  同一段会话，分别用【完整上下文】和【压缩后上下文】提问，比较回答正确率。

用法：
    python bench/context_e2e_eval.py --n 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

from app.agent.context import compact_history, make_llm_summarizer  # noqa: E402
from app.llm.factory import get_llm  # noqa: E402

ANSWER_SYSTEM = "你是一个数据分析助手。只根据下面的对话历史回答，不要编造，不要解释过程，直接给答案。"
CJK = re.compile(r"[\s，。；、：,.;:+\-（）()%]")


def norm(s: str) -> str:
    return CJK.sub("", s).lower()


@dataclass
class Case:
    name: str
    messages: list[dict]
    question: str
    expected: str


def build_case(idx: int, facts_per_conv: int = 15, filler_turns: int = 60) -> Case:
    """构造一段长会话，并针对「中间区域」的事实出题（头部原文保底救不了它）。"""
    domain_map = [
        ("门店销售", "华东区", ["A店", "B店", "C店"], "销售额", "万元"),
        ("库存周转", "华南仓", ["SKU-1001", "SKU-2207", "SKU-3315"], "库存周转天数", "天"),
        ("客服工单", "售后组", ["退款类", "物流类", "质量问题"], "首次响应时长", "分钟"),
        ("广告投放", "投放组", ["计划-甲", "计划-乙"], "ROI", "倍"),
        ("采购成本", "供应链", ["供应商甲", "供应商乙"], "采购单价", "元"),
    ]
    domain, scope, entities, metric, unit = domain_map[idx % len(domain_map)]

    facts: list[tuple[str, str, str]] = []  # (事实句, 问题, 期望答案)
    facts.append((f"{scope}的{metric}口径为最近三个月，按周拆解", "这次分析的统计口径（时间范围）是什么？", "最近三个月"))
    facts.append(("对比基准为去年同期", "对比基准是哪一期？", "去年同期"))
    facts.append((f"数据源为 warehouse_{idx % 3}.db 的 fact_{idx} 表", "数据源是哪个库？", f"warehouse_{idx % 3}.db"))
    for i, ent in enumerate(entities * 3):
        value = 10 + (idx * 7 + i * 13) % 90
        delta = ((idx + i) % 9) - 4
        facts.append((
            f"{ent} 在第 {i + 1} 期 为 {value}.{i % 5} {unit}，环比 {delta:+d}%",
            f"{ent} 第 {i + 1} 期的{metric}是多少？",
            f"{value}.{i % 5}",
        ))
    while len(facts) < facts_per_conv:
        n = len(facts)
        ent = entities[n % len(entities)]
        facts.append((f"待办 {n}：确认 {ent} 的数据是否缺失", f"待办 {n} 是什么？", ent))

    # 出题：比较两条「中间区域」的事实（跨实体、跨期），单点召回答不出来，
    # 必须两条都还在（或被正确摘要），才能判断谁更高。
    numeric = []
    for f, _, exp in facts[5:13]:
        m = re.search(r"为 (\d+\.\d) ", f)
        if m:
            numeric.append((float(m.group(1)), f, exp))
    if len(numeric) >= 2:
        a, b = numeric[(idx * 2) % (len(numeric) - 1)], numeric[(idx * 2 + 1) % len(numeric)]
        if a[0] == b[0]:
            b = numeric[0] if b is not numeric[0] else numeric[1]
        if a[0] > b[0]:
            higher_value, f_a, f_b = a[2], a[1], b[1]
        else:
            higher_value, f_a, f_b = b[2], a[1], b[1]
        question = f"对比这两项：{f_a}；{f_b}。哪个数值更高？只回答那个数字。"
        expected = higher_value
    else:
        fact_text, question, expected = facts[6]

    # 重算事实槽位（facts 数量可能因分支变化）
    total_turns = len(facts) + filler_turns
    step = max(1, total_turns // len(facts))
    slots = {min(total_turns - 1, i * step): i for i in range(len(facts))}

    msgs: list[dict] = []
    for turn in range(total_turns):
        if turn in slots:
            f = facts[slots[turn]][0]
            msgs.append({"role": "user", "content": f"补充一项：{f}，后面分析都要带上。"})
            msgs.append({"role": "assistant", "content": f"好的，已记录：{f}。"})
            continue
        ent = entities[turn % len(entities)]
        v = 20 + (turn * 37) % 70
        msgs.append({"role": "user", "content": f"再看第 {turn} 周的{ent}，{metric}大概 {v} {unit}，走势正常吗？"})
        msgs.append({"role": "assistant", "content": f"第 {turn} 周 {ent} 的{metric}为 {v} {unit}，属正常区间。"})

    return Case(name=f"{domain} #{idx}", messages=msgs, question=question, expected=expected)


async def ask(llm, context_msgs: list[dict], question: str) -> str:
    payload = list(context_msgs) + [{"role": "user", "content": question}]
    msgs = [{"role": "system", "content": ANSWER_SYSTEM}]
    for m in payload:
        msgs.append({"role": m["role"], "content": m["content"]})
    return (await llm.chat(msgs)) or ""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=12)
    parser.add_argument("--filler", type=int, default=60)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()

    llm = get_llm()
    cases = [build_case(i, filler_turns=args.filler) for i in range(args.n)]

    rows = []
    for case in cases:
        full_answer = await ask(llm, case.messages, case.question)

        compacted = await compact_history(
            case.messages, max_tokens=4000, keep_recent=8, summarize=make_llm_summarizer(llm)
        )
        comp_answer = await ask(llm, compacted.messages, case.question)

        ok_full = norm(case.expected) in norm(full_answer)
        ok_comp = norm(case.expected) in norm(comp_answer)
        rows.append({
            "case": case.name,
            "question": case.question,
            "expected": case.expected,
            "full_ok": ok_full,
            "compacted_ok": ok_comp,
            "compression": 1 - compacted.tokens_after / compacted.tokens_before,
            "full_answer": full_answer[:80],
            "compacted_answer": comp_answer[:80],
        })
        flag = "OK " if ok_comp else "MISS"
        print(f"{flag} {case.name:<14} 期望={case.expected:<14} 压缩后答={comp_answer[:40]!r}")

    full_acc = sum(r["full_ok"] for r in rows) / len(rows)
    comp_acc = sum(r["compacted_ok"] for r in rows) / len(rows)
    avg_compression = sum(r["compression"] for r in rows) / len(rows)

    print()
    print(f"完整上下文准确率: {full_acc*100:.0f}%")
    print(f"压缩后准确率:     {comp_acc*100:.0f}%")
    print(f"平均压缩率:       {avg_compression*100:.0f}%")
    print(f"样本:            {len(rows)} 段会话")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": rows, "full_acc": full_acc, "comp_acc": comp_acc}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
