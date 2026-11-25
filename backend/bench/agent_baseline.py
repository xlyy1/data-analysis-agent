"""离线 Agent 基线（CI 回归门）。

为什么需要它：`evaluate_text2sql*.py` 那几套评测要打 DeepSeek，收费且结果有随机性，
不能进 CI。但没有回归门的话，"图路由 / SQL 安全闸 / 结果校验 / 图表生成"这类
**机制性**改动一旦改坏，要等到人工演示才会发现。

所以这里用确定性 Mock LLM（`LLM_PROVIDER=mock`）+ 固定样例数据，跑通完整图，
把每条用例的关键布尔量记成基线，`--check` 时逐项比对，任何一项从 true 变 false
都会以非 0 退出码失败。

用法：
    python bench/agent_baseline.py            # 跑一遍并与 bench/agent_baseline.json 比对
    python bench/agent_baseline.py --write    # 重新生成基线（改动机制后确认无误再写）
    python bench/agent_baseline.py --json     # 只输出 JSON

注意：它检验的是**链路是否还通**，不是 NL2SQL 准确率。准确率看
`docs/perf-index.md` 里记录的 DeepSeek 评测结果（309 条用例，correct_rate=1.0）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# CI 里不允许访问外网 / 不允许用付费 Key
for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("TRACE_ENABLED", "false")
os.environ.setdefault("SAMPLE_SEED_ENABLED", "false")

from app.agent.graph import agent_app  # noqa: E402
from app.datasource.factory import create_datasource  # noqa: E402
from app.services.sample_data import build_all  # noqa: E402
from app.services.schema import describe_schema  # noqa: E402

SAMPLES = BACKEND.parent / "data" / "samples"
BASELINE_FILE = Path(__file__).resolve().parent / "agent_baseline.json"

# 5 个明确问题 + 3 个模糊问题（必须澄清）
CASES: list[dict] = [
    {"id": "bar_by_city", "question": "各城市的销售额排名", "clarify": False},
    {"id": "bar_by_channel", "question": "各渠道的销售额占比", "clarify": False},
    {"id": "diagnose_profit", "question": "哪个渠道的利润最低，为什么", "clarify": False},
    {"id": "metric_revenue", "question": "总销售额是多少", "clarify": False},
    {"id": "metric_profit", "question": "各品类的利润对比", "clarify": False},
    {"id": "vague_sales", "question": "帮我看看销售情况", "clarify": True},
    {"id": "vague_perf", "question": "最近表现怎么样", "clarify": True},
    {"id": "vague_short", "question": "分析一下", "clarify": True},
]


def _initial_state(schema_json: str, config_json: str, question: str) -> dict:
    return {
        "messages": [],
        "trace_id": "",
        "user_input": question,
        "datasource_ids": ["sample"],
        "datasource_schemas": [schema_json],
        "datasource_configs": [config_json],
        "intent": "",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
        "generated_sql": "",
        "sql_explanation": "",
        "sql_needs_confirmation": False,
        "sql_retry_count": 0,
        "sql_error": "",
        "empty_result": False,
        "result_warnings": [],
        "datasource_status": [],
        "query_result_json": "{}",
        "analysis_type": "summary",
        "analysis_summary": "",
        "diagnosis_causes": [],
        "diagnosis_evidence": [],
        "diagnosis_suggestions": [],
        "chart_config_json": "{}",
        "final_response": "",
        "error": "",
        "allow_write": False,
    }


async def _prepare() -> tuple[str, str]:
    db_path = SAMPLES / "shop.db"
    if not db_path.exists():
        build_all(SAMPLES)
    connector = create_datasource("sqlite", {"db_path": str(db_path)})
    await connector.connect()
    try:
        schema = await describe_schema(connector, use_cache=False)
    finally:
        await connector.disconnect()
    config = json.dumps({"type": "sqlite", "config": {"db_path": str(db_path)}})
    return json.dumps(schema, ensure_ascii=False), config


async def run_case(schema_json: str, config_json: str, case: dict) -> dict:
    started = time.perf_counter()
    state = await agent_app.ainvoke(_initial_state(schema_json, config_json, case["question"]))
    duration_ms = (time.perf_counter() - started) * 1000

    query_result = json.loads(state.get("query_result_json") or "{}")
    chart = json.loads(state.get("chart_config_json") or "{}")
    clarified = bool(state.get("needs_clarification"))
    sql = (state.get("generated_sql") or "").strip()
    rows = query_result.get("rows") or []

    return {
        "id": case["id"],
        "question": case["question"],
        "clarified": clarified,
        "clarification_ok": clarified == case["clarify"],
        "has_sql": bool(sql),
        "sql_only_readonly": sql.upper().startswith("SELECT") or sql == "",
        "exec_ok": not state.get("error"),
        "has_rows": len(rows) > 0,
        "has_chart": bool(chart.get("echarts_option")),
        "has_answer": bool(state.get("final_response")),
        "duration_ms": round(duration_ms, 1),
    }


async def main_async(write: bool, as_json: bool) -> int:
    if not (SAMPLES / "shop.db").exists():
        print("# 生成样例数据 ...", file=sys.stderr)
        build_all(SAMPLES)
    schema_json, config_json = await _prepare()

    results: list[dict] = []
    for case in CASES:
        results.append(await run_case(schema_json, config_json, case))

    summary = {
        "cases": len(results),
        "clarification_accuracy": round(
            sum(1 for r in results if r["clarification_ok"]) / len(results), 4
        ),
        "exec_rate": round(sum(1 for r in results if r["exec_ok"]) / len(results), 4),
        "chart_rate_on_answered": round(
            sum(1 for r in results if r["has_chart"])
            / max(1, sum(1 for r in results if not r["clarified"])),
            4,
        ),
        "readonly_sql_rate": round(sum(1 for r in results if r["sql_only_readonly"]) / len(results), 4),
        "model": os.environ.get("LLM_PROVIDER", "mock"),
    }
    payload = {"summary": summary, "cases": results}

    if write:
        BASELINE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"# 基线已写入 {BASELINE_FILE}", file=sys.stderr)

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    # ---- 回归比对 ----
    if not write and BASELINE_FILE.exists():
        expected = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        failures = compare(expected, payload)
        if failures:
            print("\n[REGRESSION] 基线回退：", file=sys.stderr)
            for item in failures:
                print(f"  - {item}", file=sys.stderr)
            return 1

    # ---- 绝对阈值（首次运行时也生效）----
    problems = []
    if summary["exec_rate"] < 1.0:
        problems.append(f"exec_rate={summary['exec_rate']} < 1.0")
    if summary["clarification_accuracy"] < 1.0:
        problems.append(f"clarification_accuracy={summary['clarification_accuracy']} < 1.0")
    if summary["readonly_sql_rate"] < 1.0:
        problems.append(f"readonly_sql_rate={summary['readonly_sql_rate']} < 1.0")
    if summary["chart_rate_on_answered"] < 0.8:
        problems.append(f"chart_rate_on_answered={summary['chart_rate_on_answered']} < 0.8")
    if problems:
        print("\n[THRESHOLD] 未达阈值：", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False))
    print("BASELINE OK")
    return 0


CHECKED_FIELDS = ("clarified", "clarification_ok", "has_sql", "exec_ok", "has_rows", "has_chart", "has_answer")


def compare(expected: dict, actual: dict) -> list[str]:
    failures: list[str] = []
    expected_cases = {case["id"]: case for case in expected.get("cases", [])}
    for case in actual["cases"]:
        reference = expected_cases.get(case["id"])
        if reference is None:
            failures.append(f"{case['id']}: 基线里没有这条用例（新增用例需 --write）")
            continue
        for field in CHECKED_FIELDS:
            if bool(reference.get(field)) and not bool(case.get(field)):
                failures.append(f"{case['id']}.{field}: true -> false")
    for key, _minimum in (
        ("exec_rate", 0.0),
        ("clarification_accuracy", 0.0),
        ("readonly_sql_rate", 0.0),
    ):
        ref = float(expected.get("summary", {}).get(key, 0.0))
        now = float(actual["summary"].get(key, 0.0))
        if now < ref:
            failures.append(f"summary.{key}: {ref} -> {now}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="重新生成基线文件")
    parser.add_argument("--json", action="store_true", help="把结果 JSON 打到 stdout")
    args = parser.parse_args()
    return asyncio.run(main_async(args.write, args.json))


if __name__ == "__main__":
    sys.exit(main())
