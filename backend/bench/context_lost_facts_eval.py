"""针对「被压缩丢掉的事实」出题：压缩到底有没有让 Agent 答错。

与 context_e2e_eval.py 的差别：
- 那个随机问中间事实（恰好可能都在），得到 100% vs 100% 的天花板结果；
- 这个先压缩、找出「确实没进新上下文」的事实，再只拿这些事实出题，
  对比【完整上下文】与【压缩后上下文】的回答，看压缩是否造成实际答题损失。

用法：
    python bench/context_lost_facts_eval.py --n 20
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

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

from app.agent.context import compact_history, make_llm_summarizer  # noqa: E402
from app.llm.factory import get_llm  # noqa: E402

ANSWER_SYSTEM = "你是一个数据分析助手。只根据下面的对话历史回答，不要编造，不要解释过程，直接给答案。"
PUNCT = re.compile(r"[\s，。；、：,.;:+\-（）()%]")


def norm(s: str) -> str:
    return PUNCT.sub("", s).lower()


@dataclass
class Fact:
    text: str
    question: str
    expected: str


DOMAINS = [
    ("门店销售", "华东区", ["A店", "B店", "C店"], "销售额", "万元"),
    ("库存周转", "华南仓", ["SKU-1001", "SKU-2207", "SKU-3315"], "库存周转天数", "天"),
    ("客服工单", "售后组", ["退款类", "物流类", "质量问题"], "首次响应时长", "分钟"),
    ("广告投放", "投放组", ["计划-甲", "计划-乙"], "ROI", "倍"),
    ("采购成本", "供应链", ["供应商甲", "供应商乙"], "采购单价", "元"),
]


def build(idx: int, facts_per_conv: int = 16, filler_turns: int = 140):
    domain, scope, entities, metric, unit = DOMAINS[idx % len(DOMAINS)]
    facts: list[Fact] = []

    facts.append(Fact(f"{scope}的{metric}口径为最近三个月，按周拆解", "这次分析统计口径的时间范围是什么？", "最近三个月"))
    facts.append(Fact("对比基准为去年同期", "对比基准是哪一期？", "去年同期"))
    facts.append(Fact(f"数据源为 warehouse_{idx % 3}.db 的 fact_{idx} 表", "数据源是哪个库？", f"warehouse_{idx % 3}.db"))

    for i, ent in enumerate(entities * 4):
        value = 10 + (idx * 11 + i * 17) % 90
        delta = ((idx + i) % 9) - 4
        facts.append(Fact(
            f"{ent} 在第 {i + 1} 期 为 {value}.{i % 5} {unit}，环比 {delta:+d}%",
            f"{ent} 第 {i + 1} 期的{metric}是多少？",
            f"{value}.{i % 5}",
        ))
    while len(facts) < facts_per_conv:
        n = len(facts)
        ent = entities[n % len(entities)]
        facts.append(Fact(f"待办 {n}：确认 {ent} 的数据是否缺失", f"待办 {n} 是什么？", ent))

    total_turns = len(facts) + filler_turns
    step = max(1, total_turns // len(facts))
    slots = {min(total_turns - 1, i * step): i for i in range(len(facts))}

    msgs: list[dict] = []
    for turn in range(total_turns):
        if turn in slots:
            f = facts[slots[turn]]
            msgs.append({"role": "user", "content": f"补充一项：{f.text}，后面分析都要带上。"})
            msgs.append({"role": "assistant", "content": f"好的，已记录：{f.text}。"})
            continue
        ent = entities[turn % len(entities)]
        v = 20 + (turn * 41) % 70
        msgs.append({"role": "user", "content": f"再看第 {turn} 周的{ent}，{metric}大概 {v} {unit}，走势正常吗？"})
        msgs.append({"role": "assistant", "content": f"第 {turn} 周 {ent} 的{metric}为 {v} {unit}，属正常区间。"})
    return domain, msgs, facts


async def ask(llm, context, question):
    msgs = [{"role": "system", "content": ANSWER_SYSTEM}]
    for m in context:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": question})
    return (await llm.chat(msgs)) or ""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--max-probes", type=int, default=3, help="每段会话最多探测几个丢失事实")
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()

    llm = get_llm()
    rows = []
    total_lost = total_facts = 0

    for idx in range(args.n):
        domain, msgs, facts = build(idx)
        compacted = await compact_history(
            msgs, max_tokens=4000, keep_recent=8, summarize=make_llm_summarizer(llm)
        )
        comp_text = norm("\n".join(m["content"] for m in compacted.messages))
        lost = [f for f in facts if norm(f.text) not in comp_text]
        total_lost += len(lost)
        total_facts += len(facts)

        for fact in lost[: args.max_probes]:
            full_ans = await ask(llm, msgs, fact.question)
            comp_ans = await ask(llm, compacted.messages, fact.question)
            rows.append({
                "case": f"{domain} #{idx}",
                "fact": fact.text,
                "expected": fact.expected,
                "full_ok": norm(fact.expected) in norm(full_ans),
                "comp_ok": norm(fact.expected) in norm(comp_ans),
                "full_answer": full_ans[:60],
                "comp_answer": comp_ans[:60],
                "compression": 1 - compacted.tokens_after / compacted.tokens_before,
            })

    if not rows:
        print("没有探测到丢失事实：压缩后所有事实都在上下文里，本实验无区分度。")
        return 0

    full_acc = sum(r["full_ok"] for r in rows) / len(rows)
    comp_acc = sum(r["comp_ok"] for r in rows) / len(rows)
    avg_comp = sum(r["compression"] for r in rows) / len(rows)

    print(f"{'OK/MISS':<9}{'会话':<14}{'问题事实':<34}{'期望':<12}{'压缩后回答'}")
    for r in rows:
        flag = "OK  " if r["comp_ok"] else "MISS"
        print(f"{flag:<9}{r['case']:<14}{r['fact'][:32]:<34}{r['expected']:<12}{r['comp_answer']!r}")

    print()
    print(f"丢失事实总数: {total_lost}/{total_facts}  ({total_lost/total_facts*100:.1f}%)")
    print(f"探测样本: {len(rows)} 条丢失事实")
    print(f"完整上下文准确率: {full_acc*100:.0f}%")
    print(f"压缩后准确率:     {comp_acc*100:.0f}%")
    print(f"平均压缩率:       {avg_comp*100:.0f}%")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": rows, "full_acc": full_acc, "comp_acc": comp_acc,
                        "lost": total_lost, "facts": total_facts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
