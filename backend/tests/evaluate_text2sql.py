"""Text-to-SQL 评测：自然语言 → 生成 SQL → 在真实数据上执行 → 与参考结果比对。

在 D:\\data-agent 下运行：
    python backend/tests/evaluate_text2sql.py --repeat 1 --temperature 0

参考值全部用 pandas 直接从源数据算出，不经过模型。
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
XLSX = Path(os.getenv("EVAL_XLSX") or (BACKEND.parent / "data" / "sales_source.xlsx"))
FALLBACK_DIR = BACKEND / "tests" / "data"

sys.path.insert(0, str(BACKEND))

# (问题, 检查类型)
CASES = [
    # --- 基础汇总 ---
    ("总销售额是多少", "scalar"),
    ("总销量是多少", "scalar"),
    ("总利润是多少", "scalar"),
    ("总成本是多少", "scalar"),
    ("订单数一共多少", "scalar"),
    ("平均订单金额是多少", "scalar"),
    ("平均单价是多少", "scalar"),
    ("整体毛利率是多少", "scalar"),
    ("整体利润率是多少", "scalar"),
    ("有多少笔订单是亏损的", "scalar"),
    # --- 时间维度 ---
    ("2026年1月的销售额合计是多少", "scalar"),
    ("2026年1月的销量是多少", "scalar"),
    ("2026年1月有多少笔订单", "scalar"),
    ("2026年3月的利润是多少", "scalar"),
    ("2026年5月的销售额是多少", "scalar"),
    ("每个月分别卖了多少钱", "row_count"),
    ("2026年1月和2月的销售额分别是多少", "row_count"),
    ("2026年4月的毛利率是多少", "scalar"),
    ("2026年2月淘宝的销售额是多少", "scalar"),
    ("数据覆盖了哪几个月的销售", "row_count"),
    # --- 维度分组 ---
    ("各销售渠道的销售额是多少", "row_count"),
    ("各产品类别的销量是多少", "row_count"),
    ("各城市的订单数是多少", "row_count"),
    ("每个产品的销售额分别是多少", "row_count"),
    ("销售额最高的渠道是哪个", "top_name"),
    ("销量最低的渠道是哪个", "top_name"),
    ("一共有几个销售渠道", "scalar"),
    ("一共几个产品类别", "scalar"),
    # --- TopN ---
    ("销量最大的产品是哪个", "top_name"),
    ("利润最高的产品是哪个", "top_name"),
    ("成本最高的三个产品", "top3_names"),
    ("销售额最低的产品是哪个", "top_name"),
    ("单价最高的产品是哪个", "top_name"),
    ("销量前三的产品", "top3_names"),
    ("销售额前三的产品", "top3_names"),
    ("利润最低的产品是哪个", "top_name"),
    # --- 比率 ---
    ("淘宝渠道的毛利率是多少", "scalar"),
    ("京东渠道的毛利率是多少", "scalar"),
    ("手机配件类别的毛利率是多少", "scalar"),
    ("音频设备类别的毛利率是多少", "scalar"),
    ("淘宝渠道销售额占总销售额的比例是多少", "scalar"),
    # --- 组合条件 ---
    ("2026年1月淘宝的销售额是多少", "scalar"),
    ("2026年1月京东的销量是多少", "scalar"),
    ("上海的订单数是多少", "scalar"),
    ("重庆的销售额是多少", "scalar"),
    ("手机配件的总销量是多少", "scalar"),
    ("充电宝的总销量是多少", "scalar"),
    ("淘宝渠道的总利润是多少", "scalar"),
    # --- 边界 ---
    ("2026年12月的销售额是多少", "scalar_or_empty"),
    ("哪个产品类别的利润率最低", "top_name"),
    # --- 补充比率与口径 ---
    ("哪个产品的利润率最高", "top_name"),
    ("京东渠道的利润率是多少", "scalar"),
    ("2026年2月的毛利率是多少", "scalar"),
    ("音频设备的利润率是多少", "scalar"),
    ("成本占销售额的比例是多少", "scalar"),
    ("充电宝的利润率是多少", "scalar"),
    ("音频设备的利润是多少", "scalar"),
    ("运动耳机的销量是多少", "scalar"),
    ("手机配件的订单数是多少", "scalar"),
    ("充电宝的成本是多少", "scalar"),
]


def build_reference(df):
    """用 pandas 直接算参考值，不经过模型。"""
    import pandas as pd

    d = df.copy()
    d["订单日期"] = pd.to_datetime(d["订单日期"])
    d["月"] = d["订单日期"].dt.month
    sales, profit, cost = d["销售额(元)"], d["利润(元)"], d["成本(元)"]

    def margin(sub) -> float:
        return float(sub["利润(元)"].sum() / sub["销售额(元)"].sum() * 100)

    ref = {}
    ref["总销售额是多少"] = ("scalar", float(sales.sum()))
    ref["总销量是多少"] = ("scalar", float(d["销量"].sum()))
    ref["总利润是多少"] = ("scalar", float(profit.sum()))
    ref["总成本是多少"] = ("scalar", float(cost.sum()))
    ref["订单数一共多少"] = ("scalar", float(len(d)))
    ref["平均订单金额是多少"] = ("scalar", float(sales.mean()))
    ref["平均单价是多少"] = ("scalar", float(d["单价(元)"].mean()))
    ref["整体毛利率是多少"] = ("scalar", margin(d))
    ref["整体利润率是多少"] = ("scalar", margin(d))
    ref["有多少笔订单是亏损的"] = ("scalar", float((profit < 0).sum()))

    ref["2026年1月的销售额合计是多少"] = ("scalar", float(d[d["月"] == 1]["销售额(元)"].sum()))
    ref["2026年1月的销量是多少"] = ("scalar", float(d[d["月"] == 1]["销量"].sum()))
    ref["2026年1月有多少笔订单"] = ("scalar", float((d["月"] == 1).sum()))
    ref["2026年3月的利润是多少"] = ("scalar", float(d[d["月"] == 3]["利润(元)"].sum()))
    ref["2026年5月的销售额是多少"] = ("scalar", float(d[d["月"] == 5]["销售额(元)"].sum()))
    ref["每个月分别卖了多少钱"] = ("row_count", float(d["月"].nunique()))
    ref["2026年1月和2月的销售额分别是多少"] = ("row_count", 2.0)
    ref["2026年4月的毛利率是多少"] = ("scalar", margin(d[d["月"] == 4]))
    ref["2026年2月淘宝的销售额是多少"] = (
        "scalar", float(d[(d["月"] == 2) & (d["销售渠道"] == "淘宝")]["销售额(元)"].sum()))
    ref["数据覆盖了哪几个月的销售"] = ("row_count", float(d["月"].nunique()))

    ref["各销售渠道的销售额是多少"] = ("row_count", float(d["销售渠道"].nunique()))
    ref["各产品类别的销量是多少"] = ("row_count", float(d["产品类别"].nunique()))
    ref["各城市的订单数是多少"] = ("row_count", float(d["客户城市"].nunique()))
    ref["每个产品的销售额分别是多少"] = ("row_count", float(d["产品名称"].nunique()))
    ref["销售额最高的渠道是哪个"] = (
        "top_name", d.groupby("销售渠道")["销售额(元)"].sum().idxmax())
    ref["销量最低的渠道是哪个"] = (
        "top_name", d.groupby("销售渠道")["销量"].sum().idxmin())
    ref["一共有几个销售渠道"] = ("scalar", float(d["销售渠道"].nunique()))
    ref["一共几个产品类别"] = ("scalar", float(d["产品类别"].nunique()))

    ref["销量最大的产品是哪个"] = ("top_name", d.groupby("产品名称")["销量"].sum().idxmax())
    ref["利润最高的产品是哪个"] = ("top_name", d.groupby("产品名称")["利润(元)"].sum().idxmax())
    ref["成本最高的三个产品"] = (
        "top3_names", list(d.groupby("产品名称")["成本(元)"].sum().nlargest(3).index))
    ref["销售额最低的产品是哪个"] = (
        "top_name", d.groupby("产品名称")["销售额(元)"].sum().idxmin())
    ref["单价最高的产品是哪个"] = ("top_name", d.loc[d["单价(元)"].idxmax(), "产品名称"])
    ref["销量前三的产品"] = (
        "top3_names", list(d.groupby("产品名称")["销量"].sum().nlargest(3).index))
    ref["销售额前三的产品"] = (
        "top3_names", list(d.groupby("产品名称")["销售额(元)"].sum().nlargest(3).index))
    ref["利润最低的产品是哪个"] = ("top_name", d.groupby("产品名称")["利润(元)"].sum().idxmin())

    ref["淘宝渠道的毛利率是多少"] = ("scalar", margin(d[d["销售渠道"] == "淘宝"]))
    ref["京东渠道的毛利率是多少"] = ("scalar", margin(d[d["销售渠道"] == "京东"]))
    ref["手机配件类别的毛利率是多少"] = ("scalar", margin(d[d["产品类别"] == "手机配件"]))
    ref["音频设备类别的毛利率是多少"] = ("scalar", margin(d[d["产品类别"] == "音频设备"]))
    ref["淘宝渠道销售额占总销售额的比例是多少"] = (
        "scalar", float(d[d["销售渠道"] == "淘宝"]["销售额(元)"].sum() / sales.sum() * 100))

    ref["2026年1月淘宝的销售额是多少"] = (
        "scalar", float(d[(d["月"] == 1) & (d["销售渠道"] == "淘宝")]["销售额(元)"].sum()))
    ref["2026年1月京东的销量是多少"] = (
        "scalar", float(d[(d["月"] == 1) & (d["销售渠道"] == "京东")]["销量"].sum()))
    ref["上海的订单数是多少"] = ("scalar", float((d["客户城市"] == "上海").sum()))
    ref["重庆的销售额是多少"] = ("scalar", float(d[d["客户城市"] == "重庆"]["销售额(元)"].sum()))
    ref["手机配件的总销量是多少"] = ("scalar", float(d[d["产品类别"] == "手机配件"]["销量"].sum()))
    ref["充电宝的总销量是多少"] = ("scalar", float(d[d["产品名称"] == "充电宝"]["销量"].sum()))
    ref["淘宝渠道的总利润是多少"] = ("scalar", float(d[d["销售渠道"] == "淘宝"]["利润(元)"].sum()))

    ref["2026年12月的销售额是多少"] = ("scalar", 0.0)
    ref["哪个产品的利润率最高"] = (
        "top_name",
        (d.groupby("产品名称").apply(lambda s: s["利润(元)"].sum() / s["销售额(元)"].sum()))
        .idxmax(),
    )
    ref["京东渠道的利润率是多少"] = ("scalar", margin(d[d["销售渠道"] == "京东"]))
    ref["2026年2月的毛利率是多少"] = ("scalar", margin(d[d["月"] == 2]))
    ref["音频设备的利润率是多少"] = ("scalar", margin(d[d["产品类别"] == "音频设备"]))
    ref["成本占销售额的比例是多少"] = ("scalar", float(cost.sum() / sales.sum() * 100))
    ref["充电宝的利润率是多少"] = ("scalar", margin(d[d["产品名称"] == "充电宝"]))
    ref["音频设备的利润是多少"] = ("scalar", float(d[d["产品类别"] == "音频设备"]["利润(元)"].sum()))
    ref["运动耳机的销量是多少"] = ("scalar", float(d[d["产品名称"] == "运动耳机"]["销量"].sum()))
    ref["手机配件的订单数是多少"] = ("scalar", float((d["产品类别"] == "手机配件").sum()))
    ref["充电宝的成本是多少"] = ("scalar", float(d[d["产品名称"] == "充电宝"]["成本(元)"].sum()))
    ref["哪个产品类别的利润率最低"] = (
        "top_name",
        (d.groupby("产品类别").apply(lambda s: s["利润(元)"].sum() / s["销售额(元)"].sum()))
        .idxmin(),
    )
    return ref


METRIC_COLUMNS = {
    "销售额": "销售额(元)",
    "销量": "销量",
    "利润": "利润(元)",
    "成本": "成本(元)",
}


def expand_cases(df, ref):
    """按 维度 × 指标 组合生成用例，参考值用 pandas 直接算。"""
    import pandas as pd

    d = df.copy()
    d["订单日期"] = pd.to_datetime(d["订单日期"])
    d["月"] = d["订单日期"].dt.month
    generated = []

    def add(question, kind, expected):
        if question in ref:
            return
        ref[question] = (kind, expected)
        generated.append((question, kind))

    # 维度 × 指标（求和）
    for dim in ("销售渠道", "产品类别", "产品名称"):
        for value in sorted(d[dim].dropna().unique()):
            subset = d[d[dim] == value]
            if subset.empty:
                continue
            for label, column in METRIC_COLUMNS.items():
                add(f"{value}的{label}是多少", "scalar",
                    float(subset[column].sum()))

    # 月份 × 指标
    for month in sorted(d["月"].unique()):
        subset = d[d["月"] == month]
        for label, column in METRIC_COLUMNS.items():
            add(f"2026年{int(month)}月的{label}是多少", "scalar",
                float(subset[column].sum()))

    # 城市 × 两个指标
    for city in sorted(d["客户城市"].dropna().unique()):
        subset = d[d["客户城市"] == city]
        add(f"{city}的销售额是多少", "scalar", float(subset["销售额(元)"].sum()))
        add(f"{city}的订单数是多少", "scalar", float(len(subset)))

    # 维度 × 月份（双条件，明显更难）
    for dim in ("销售渠道", "产品类别"):
        for value in sorted(d[dim].dropna().unique()):
            for month in sorted(d["月"].unique()):
                subset = d[(d[dim] == value) & (d["月"] == month)]
                if subset.empty:
                    continue
                add(f"2026年{int(month)}月{value}的销售额是多少", "scalar",
                    float(subset["销售额(元)"].sum()))

    # 维度利润率
    for dim in ("销售渠道", "产品类别"):
        for value in sorted(d[dim].dropna().unique()):
            subset = d[d[dim] == value]
            if subset.empty or not subset["销售额(元)"].sum():
                continue
            add(f"{value}的利润率是多少", "scalar",
                float(subset["利润(元)"].sum() / subset["销售额(元)"].sum() * 100))

    return generated


def check(kind, expected, columns, rows):
    """返回 (是否通过, 说明)"""
    if kind == "scalar_or_empty":
        if not rows:
            return True, "无结果行，视为无数据"
        has_number = any(
            v is not None and not isinstance(v, bool) and str(v).replace(",", "").strip("%").replace("-", "").replace(".", "").isdigit()
            for row in rows for v in row
        )
        if not has_number:
            return True, "结果为 NULL，视为无数据"
        kind = "scalar"
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

    if not XLSX.exists():
        raise SystemExit(
            f"找不到评测源数据：{XLSX}\n"
            "这个评测依赖原始 Excel（未入库）。两种方式提供：\n"
            "  1) 设置环境变量 EVAL_XLSX=/path/to/源数据.xlsx\n"
            "  2) 把文件放到 <repo>/data/sales_source.xlsx\n"
            "回归用的历史结果已归档在 tests/data/text2sql.result.json，"
            "CI 走 bench/quality_gate.py 校验，不需要重跑本脚本。"
        )
    ds = ExcelDataSource(file_path=str(XLSX), file_name=XLSX.name)
    await ds.connect()
    ds.auto_add_total_columns()
    from app.services.schema import describe_schema

    schema = await describe_schema(ds)
    schema_text = json.dumps(schema, ensure_ascii=False)

    import pandas as pd
    raw = pd.read_excel(XLSX, sheet_name=0)
    ref = build_reference(raw)
    extra = expand_cases(raw, ref)
    all_cases = CASES + extra

    rows_out = []
    per_case = {q: [] for q, _ in all_cases}
    run_rate = []
    for run_idx in range(args.repeat):
        run_hits = 0
        for q, kind in all_cases:
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
            if kind == "scalar_or_empty" and not ok_exec and "结果为空" in err:
                ok, detail = True, "无结果行，视为无数据"
            per_case[q].append((ok_exec, ok, detail, sql, gen_ms))
            run_hits += ok
            if args.verbose:
                print(f'[run {run_idx + 1}][{"OK " if ok else "MISS"}] {q} | {detail}')
        run_rate.append(round(run_hits / len(all_cases), 4))

    await ds.disconnect()

    flips = []
    for q, kind in all_cases:
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
