"""上下文压缩的信息留存评测。

用法：
    python bench/context_retention_eval.py            # 24 段会话，LLM + 兜底各跑一遍
    python bench/context_retention_eval.py --n 40     # 自定义会话数
    python bench/context_retention_eval.py --no-llm   # 只测抽取式兜底（不花钱）

评测口径：
- 每段会话埋 8 个「事实」（门店/商品名 + 数字 + 口径 + 待办 + 表名）；
- 事实只出现在前若干轮，后面用重复追问把它挤出近窗，确保检验的是摘要而不是原文；
- 压缩后对全文做归一化（去空白与标点）子串匹配，命中即认为保留；
- 同时记录 token 压缩率、耗时、失败降级次数。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

from app.agent.context import compact_history, make_llm_summarizer  # noqa: E402
from app.llm.factory import get_llm  # noqa: E402

# --- 事实模板：不同业务域，避免只测一种句式 ---
DOMAINS = [
    ("门店销售", "华东区", ["A店", "B店", "C店"], "销售额", "万元"),
    ("库存周转", "华南仓", ["SKU-1001", "SKU-2207", "SKU-3315"], "库存周转天数", "天"),
    ("客服工单", "售后组", ["退款类", "物流类", "质量问题"], "首次响应时长", "分钟"),
    ("广告投放", "投放组", ["计划-甲", "计划-乙"], "ROI", "倍"),
    ("采购成本", "供应链", ["供应商甲", "供应商乙"], "采购单价", "元"),
]

FILLER_Q = "再帮我把上周的情况按同样方式拆一遍，看看走势有没有变化，顺便标注异常项。"
FILLER_A = "已按同样口径拆解上周数据：整体走势与前期一致，个别项有小幅波动，异常项已标注。"


def filler_turn(i: int, entities: list[str], metric: str, unit: str) -> tuple[str, str]:
    """填充轮刻意做到每轮都不同：真实长会话不会反复问同一句话，去重救不了预算。"""
    ent = entities[i % len(entities)]
    value = 20 + (i * 37) % 70
    q = (
        f"再看第 {i} 周的{ent}，{metric}大概 {value} {unit} 左右，"
        f"帮我判断这个走势是否正常，要不要拆到日级别看看。"
    )
    a = (
        f"第 {i} 周 {ent} 的{metric}为 {value} {unit}，"
        f"与前一周相比波动 {((i % 7) - 3):+d}%，属于正常区间，暂不需要拆到日级别。"
    )
    return q, a


def norm(s: str) -> str:
    return re.sub(r"[\s，。；、：,.;:+\-（）()%]", "", s).lower()


@dataclass
class Conversation:
    name: str
    messages: list[dict]
    facts: list[str] = field(default_factory=list)


def build_conversation(idx: int, facts_per_conv: int = 8, filler_turns: int = 70) -> Conversation:
    domain, scope, entities, metric, unit = DOMAINS[idx % len(DOMAINS)]
    facts: list[str] = []

    facts.append(f"{scope}的{metric}口径为最近三个月，按周拆解")
    facts.append("对比基准为去年同期")
    facts.append(f"数据源为 warehouse_{idx % 3}.db 的 fact_{metric} 表")

    for i, ent in enumerate(entities[:3]):
        value = 10 + (idx * 7 + i * 13) % 90
        delta = ((idx + i) % 9) - 4
        facts.append(f"{ent} 为 {value}.{i} {unit}，环比 {delta:+d}%")

    while len(facts) < facts_per_conv:
        n = len(facts)
        facts.append(f"待办 {n}：确认 {entities[n % len(entities)]} 的数据是否缺失")

    msgs: list[dict] = []
    # 事实均匀分布在整段会话里：否则「保头」策略会全部命中，测不出摘要的价值
    total_turns = facts_per_conv + filler_turns
    fact_slots = set()
    step = max(1, total_turns // max(1, facts_per_conv))
    for i in range(facts_per_conv):
        fact_slots.add(min(total_turns - 1, i * step))

    fact_iter = iter(facts)
    for turn in range(total_turns):
        if turn in fact_slots:
            try:
                f = next(fact_iter)
            except StopIteration:
                f = None
            if f:
                msgs.append({"role": "user", "content": f"补充一项：{f}，后面分析都要带上。"})
                msgs.append({"role": "assistant", "content": f"好的，已记录：{f}。"})
                continue
        q, a = filler_turn(turn, entities, metric, unit)
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": a})
    return Conversation(name=f"{domain} #{idx}", messages=msgs, facts=facts)


def score(text: str, facts: list[str]) -> tuple[list[str], list[str]]:
    t = norm(text)
    hit = [f for f in facts if norm(f) in t]
    miss = [f for f in facts if norm(f) not in t]
    return hit, miss


async def run_path(name: str, convs: list[Conversation], summarize):
    per_conv = []
    total_hit = total_facts = 0
    tokens_before = tokens_after = 0
    fallbacks = 0
    latencies = []

    for conv in convs:
        t0 = time.perf_counter()
        result = await compact_history(
            conv.messages,
            max_tokens=4000,
            keep_recent=8,
            summarize=summarize,
        )
        latencies.append((time.perf_counter() - t0) * 1000)

        text = "\n".join(m["content"] for m in result.messages)
        hit, miss = score(text, conv.facts)
        per_conv.append(len(hit) / len(conv.facts))
        total_hit += len(hit)
        total_facts += len(conv.facts)
        tokens_before += result.tokens_before
        tokens_after += result.tokens_after
        if summarize is not None and not result.used_llm:
            fallbacks += 1

    return {
        "path": name,
        "conversations": len(convs),
        "facts": total_facts,
        "fact_hit": total_hit,
        "retention": total_hit / total_facts,
        "retention_min": min(per_conv),
        "retention_median": statistics.median(per_conv),
        "compression": 1 - tokens_after / tokens_before,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
        "fallbacks": fallbacks,
        "per_conversation": per_conv,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=24, help="会话数")
    parser.add_argument("--facts", type=int, default=8, help="每段会话的事实数")
    parser.add_argument("--filler", type=int, default=70, help="填充轮数")
    parser.add_argument("--no-llm", action="store_true", help="只测兜底")
    parser.add_argument("--json", type=str, default="", help="结果写入的 JSON 路径")
    args = parser.parse_args()

    convs = [build_conversation(i, args.facts, args.filler) for i in range(args.n)]
    print(f"评测集：{args.n} 段会话 × {args.facts} 个事实 = {args.n * args.facts} 个事实实例")

    results = []
    results.append(await run_path("抽取式兜底", convs, None))

    if not args.no_llm:
        llm = get_llm()
        results.append(await run_path("LLM 结构化摘要", convs, make_llm_summarizer(llm)))

    header = f"{'路径':<16}{'留存':>8}{'最低':>8}{'中位':>8}{'压缩率':>9}{'耗时(ms)':>11}{'降级':>6}"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['path']:<16}{r['retention']*100:>7.1f}%{r['retention_min']*100:>7.0f}%"
            f"{r['retention_median']*100:>7.0f}%{r['compression']*100:>8.0f}%"
            f"{r['avg_latency_ms']:>11.0f}{r['fallbacks']:>6}"
        )

    print(f"\n事实实例：{results[0]['facts']} 个")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
