"""澄清能力评测：跑 understand_intent，统计反问是否发生在该发生的时侯。

支持多次重复 + 逐题多数表决，避免 LLM 抖动导致单次结论不可复现。

在 D:\\data-agent 下运行：
    python backend/tests/evaluate_clarification.py --dataset backend/tests/data/clarification_boundary.json --repeat 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
DATASET = HERE.parent / "data" / "clarification_eval.json"
FALLBACK_DIR = Path(r"C:\Users\dly20\Documents\deepseek-harness\default-workspace\resume-rebuild\results")

sys.path.insert(0, str(BACKEND))


async def run_one(text: str, schema: str) -> dict:
    from app.agent.nodes.understand import understand_intent

    state = {"user_input": text, "datasource_schemas": [schema], "history": []}
    out = await understand_intent(state)
    if out.get("error"):
        return {"error": out["error"]}
    return {
        "needs_clarification": bool(out.get("needs_clarification")),
        "analysis_type": out.get("analysis_type"),
        "question": (out.get("clarification_question") or "")[:60],
    }


def metrics(rows, key):
    fuzzy = [r for r in rows if r["expect_clarify"]]
    clear = [r for r in rows if not r["expect_clarify"]]
    caught = sum(1 for r in fuzzy if r.get(key) is True)
    false_alarm = sum(1 for r in clear if r.get(key) is True)
    unknown = sum(1 for r in rows if r.get(key) is None)
    return {
        "fuzzy_count": len(fuzzy),
        "clear_count": len(clear),
        "clarify_recall": round(caught / len(fuzzy), 4) if fuzzy else 0.0,
        "false_clarify_rate": round(false_alarm / len(clear), 4) if clear else 0.0,
        "accuracy": round(sum(1 for r in rows if r.get(key) == r["expect_clarify"]) / len(rows), 4),
        "unknown": unknown,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=DATASET)
    ap.add_argument("--repeat", type=int, default=3, help="同一套题跑几次，逐题取多数")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    os.environ["LLM_TEMPERATURE"] = str(args.temperature)

    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    schema = data["schema"]
    items = data["items"]

    per_item = {it["id"]: [] for it in items}
    run_acc = []

    for run_idx in range(args.repeat):
        rows = []
        for it in items:
            res = await run_one(it["text"], schema)
            pred = None if "error" in res else res["needs_clarification"]
            per_item[it["id"]].append(pred)
            rows.append({**it, "pred": pred, "error": res.get("error"),
                         "type": None if "error" in res else res.get("analysis_type")})
        m = metrics(rows, "pred")
        run_acc.append(m["accuracy"])
        if args.verbose:
            print(f"[run {run_idx + 1}] acc={m['accuracy']} recall={m['clarify_recall']} "
                  f"fpr={m['false_clarify_rate']}")

    rows = []
    for it in items:
        votes = [v for v in per_item[it["id"]] if v is not None]
        majority = (sum(votes) * 2 > len(votes)) if votes else None
        rows.append({**it, "votes": votes, "pred": majority,
                     "flipped": len(set(votes)) > 1})

    summary = {
        "dataset": args.dataset.stem,
        "repeat": args.repeat,
        "temperature": args.temperature,
        "runs_accuracy": run_acc,
        "majority": metrics(rows, "pred"),
        "flipped_items": [{"id": r["id"], "text": r["text"], "expect": r["expect_clarify"],
                           "votes": r["votes"]} for r in rows if r["flipped"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    payload = json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2)
    out = args.output or (FALLBACK_DIR / f"{args.dataset.stem}.repeat{args.repeat}.json")
    saved = None
    for candidate in (out, FALLBACK_DIR / out.name, HERE.parent / "data" / out.name):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(payload, encoding="utf-8")
            saved = candidate
            break
        except OSError as error:
            print(f"[warn] {candidate} 不可写: {error}")
    print(f"[saved] {saved}" if saved else "[warn] 结果未落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
