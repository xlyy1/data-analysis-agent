"""Text-to-SQL 评测：自然语言 → 生成 SQL → 在真实数据上执行 → 与参考结果比对。

在 D:\\data-agent 下运行：
    python backend/tests/evaluate_text2sql.py --repeat 1 --temperature 0
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
XLSX = Path(r"D:\data-agent\_app_data_所有对话_主对话_销售数据 (1).xlsx")
FALLBACK_DIR = Path(r"C:\Users\dly20\Documents\deepseek-harness\default-workspace\resume-rebuild\results")

sys.path.insert(0, str(BACKEND))

# (问题, 检查类型, 参考值说明)
CASES = [
    ("2026年1月的销售额合计是多少", "scalar"),
    ("销量最大的产品是哪个", "top_name"),
    ("整体毛利率是多少", "scalar"),
    ("成本最高的三个产品", "top3_names"),
    ("平均单价是多少", "scalar"),
    ("订单数一共多少", "scalar"),
    ("利润最低的产品是哪个", "top_name"),
    ("总利润是多少", "scalar"),
    ("淘宝渠道的销量总计是多少", "scalar"),
    ("各销售渠道的销售额占比", "row_count"),
    ("2026年1月和2月的销售额分别是多少", "row_count"),
]


def build_reference(df):
    """用 pandas 直接算参考值，不经过模型。"""
    import pandas as pd

    d = df.copy()
    d["订单日期"] = pd.to_datetime(d["订单日期"])
    d["月"] = d["订单日期"].dt.month

    ref = {}
    ref["2026年1月的销售额合计是多少"] = ("scalar", float(d[d["月"] == 1]["销售额(元)"].sum()))
    ref["销量最大的产品是哪个"] = (
        "top_name", d.groupby("产品名称")["销量"].sum().idxmax())
    ref["整体毛利率是多少"] = (
        "scalar", float(d["利润(元)"].sum() / d["销售额(元)"].sum() * 100))
    ref["成本最高的三个产品"] = (
        "top3_names", list(d.groupby("产品名称")["成本(元)"].sum().nlargest(3).index))
    ref["平均单价是多少"] = ("scalar", float(d["单价(元)"].mean()))
    ref["订单数一共多少"] = ("scalar", float(len(d)))
    ref["利润最低的产品是哪个"] = (
        "top_name", d.groupby("产品名称")["利润(元)"].sum().idxmin())
    ref["总利润是多少"] = ("scalar", float(d["利润(元)"].sum()))
    ref["淘宝渠道的销量总计是多少"] = (
        "scalar", float(d[d["销售渠道"] == "淘宝"]["销量"].sum()))
    ref["各销售渠道的销售额占比"] = (
        "row_count", float(d["销售渠道"].nunique()))
    ref["2026年1月和2月的销售额分别是多少"] = ("row_count", 2.0)
    return ref


def check(kind, expected, columns, rows):
    """返回 (是否通过, 说明)"""
    if not rows:
        return False, "无结果行"
    flat = [r for row in rows for r in row]
    if kind == "scalar":
        nums = []
        for v in flat:
            if isinstance(v, bool) or v is None:
                continue
            try:
                nums.append(float(str(v).replace(",", "").strip("%")))
            except (TypeError, ValueError):
                continue
        if not nums:
            return False, "结果中没有数值"
        got = max(nums, key=abs)
        tol = max(abs(expected) * 0.01, 0.5)
        return abs(got - expected) <= tol, f"期望≈{expected:.2f} 实得≈{got:.2f}"
    if kind == "top_name":
        got = str(rows[0][0])
        return expected in got or got in str(expected), f"期望包含「{expected}」实得「{got}」"
    if kind == "top3_names":
        got = [str(r[0]) for r in rows[:3]]
        hit = len(set(expected) & set(got))
        return hit >= 2, f"期望前三{expected} 实得{got}"
    if kind == "row_count":
        return abs(len(rows) - expected) <= 1, f"期望{int(expected)}行 实得{len(rows)}行"
    return False, "未知检查类型"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    os.environ["LLM_TEMPERATURE"] = str(args.temperature)

    from app.agent.nodes.query import generate_query
    from app.datasource.excel import ExcelDataSource

    ds = ExcelDataSource(file_path=str(XLSX), file_name=XLSX.name)
    await ds.connect()
    ds.auto_add_total_columns()
    tables = await ds.get_tables()
    schema = {
        "tables": [
            {
                "name": t.name,
                "row_count": t.row_count,
                "columns": [{"name": c.name, "dtype": c.dtype} for c in t.columns],
            }
            for t in tables
        ]
    }
    schema_text = json.dumps(schema, ensure_ascii=False)

    import pandas as pd
    ref = build_reference(pd.read_excel(XLSX, sheet_name=0))

    rows_out = []
    per_case = {q: [] for q, _ in CASES}
    run_rate = []
    for run_idx in range(args.repeat):
        run_hits = 0
        for q, kind in CASES:
            state = {"user_input": q, "datasource_schemas": [schema_text], "intent": "{}"}
            t0 = time.perf_counter()
            out = await generate_query(state)
            gen_ms = (time.perf_counter() - t0) * 1000
            sql = out.get("generated_sql", "")
            ok_exec, err, cols, rows = False, "", [], []
            if sql:
                try:
                    res = await ds.execute_query(sql)
                    ok_exec, cols, rows = bool(res.rows), res.columns, res.rows
                    if not res.rows:
                        err = "执行成功但结果为空"
                except Exception as e:
                    err = f"执行失败: {e}"
            else:
                err = out.get("error", "未生成 SQL")

            ok, detail = (False, err) if not ok_exec else check(kind, ref[q][1], cols, rows)
            per_case[q].append((ok_exec, ok, detail, sql, gen_ms))
            run_hits += ok
            if args.verbose:
                print(f'[run {run_idx + 1}][{"OK " if ok else "MISS"}] {q} | {detail}')
        run_rate.append(round(run_hits / len(CASES), 4))

    await ds.disconnect()

    flips = []
    for q, kind in CASES:
        results = per_case[q]
        n_ok = sum(1 for _, ok, *_ in results if ok)
        majority_ok = n_ok * 2 > len(results)
        exec_ok = any(e for e, *_ in results)
        detail = results[-1][2]
        sql = results[-1][3]
        gen_ms = sum(r[4] for r in results) / len(results)
        rows_out.append({"q": q, "kind": kind, "sql": sql, "exec_ok": exec_ok,
                         "correct": majority_ok, "detail": detail,
                         "gen_ms": round(gen_ms, 1), "runs": n_ok})
        if 0 < n_ok < len(results):
            flips.append({"q": q, "ok_runs": n_ok, "of": len(results)})

    n = len(rows_out)
    summary = {
        "cases": n,
        "repeat": args.repeat,
        "runs_correct_rate": run_rate,
        "exec_rate": round(sum(r["exec_ok"] for r in rows_out) / n, 4),
        "correct_rate": round(sum(r["correct"] for r in rows_out) / n, 4),
        "avg_gen_ms": round(sum(r["gen_ms"] for r in rows_out) / n, 1),
        "temperature": args.temperature,
        "flipped_cases": flips,
        "misses": [{"q": r["q"], "detail": r["detail"], "sql": r["sql"]}
                   for r in rows_out if not r["correct"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    payload = json.dumps({"summary": summary, "rows": rows_out}, ensure_ascii=False, indent=2)
    out_path = args.output or FALLBACK_DIR / "text2sql.result.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(f"[saved] {out_path}")
    except OSError as e:
        print(f"[warn] 未落盘: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
