"""规模化 Text-to-SQL 评测：3 万行订单 + 产品维表（需 JOIN）。

与 evaluate_text2sql.py 的区别：
- 数据量从 50 行提升到 30000 行
- 涉及两张表，金额列需要 JOIN 产品维表计算
- 参考值用 SQL 直查数据库（pandas 侧独立计算）

运行：
    python backend/tests/evaluate_text2sql_scale.py --repeat 1 --temperature 0
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
DB = BACKEND / "data" / "sales_large.db"
OUT_DIR = BACKEND / "tests" / "data"

sys.path.insert(0, str(BACKEND))

# (问题, 检查类型, 参考 SQL)
CASES = [
    ("一共有多少笔订单", "scalar", "SELECT COUNT(*) FROM orders"),
    ("总销售额是多少", "scalar", "SELECT SUM(销售额) FROM orders"),
    ("总利润是多少", "scalar", "SELECT SUM(利润) FROM orders"),
    ("总成本是多少", "scalar", "SELECT SUM(成本) FROM orders"),
    ("总销量是多少", "scalar", "SELECT SUM(销量) FROM orders"),
    ("平均订单金额是多少", "scalar", "SELECT AVG(销售额) FROM orders"),
    ("2026年3月的销售额是多少", "scalar",
     "SELECT SUM(销售额) FROM orders WHERE 订单日期 LIKE '2026-03%'"),
    ("2026年6月的订单数是多少", "scalar",
     "SELECT COUNT(*) FROM orders WHERE 订单日期 LIKE '2026-06%'"),
    ("2026年11月的利润是多少", "scalar",
     "SELECT SUM(利润) FROM orders WHERE 订单日期 LIKE '2026-11%'"),
    ("每个月分别有多少订单", "row_count",
     "SELECT substr(订单日期,1,7) m, COUNT(*) FROM orders GROUP BY m"),
    ("各销售渠道的销售额是多少", "row_count",
     "SELECT 销售渠道, SUM(销售额) FROM orders GROUP BY 销售渠道"),
    ("各城市的订单数是多少", "row_count",
     "SELECT 客户城市, COUNT(*) FROM orders GROUP BY 客户城市"),
    ("各产品类别的销量是多少", "row_count",
     "SELECT p.产品类别, SUM(o.销量) FROM orders o JOIN products p ON o.产品ID=p.产品ID GROUP BY p.产品类别"),
    ("销量最高的产品是哪个", "top_name",
     "SELECT p.产品名称 FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "GROUP BY p.产品名称 ORDER BY SUM(o.销量) DESC LIMIT 1"),
    ("销售额最高的渠道是哪个", "top_name",
     "SELECT 销售渠道 FROM orders GROUP BY 销售渠道 ORDER BY SUM(销售额) DESC LIMIT 1"),
    ("利润最高的产品是哪个", "top_name",
     "SELECT p.产品名称 FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "GROUP BY p.产品名称 ORDER BY SUM(o.利润) DESC LIMIT 1"),
    ("销售额前三的产品", "top3_names",
     "SELECT p.产品名称 FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "GROUP BY p.产品名称 ORDER BY SUM(o.销售额) DESC LIMIT 3"),
    ("销量最低的类别是哪个", "top_name",
     "SELECT p.产品类别 FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "GROUP BY p.产品类别 ORDER BY SUM(o.销量) ASC LIMIT 1"),
    ("整体利润率是多少", "scalar", "SELECT SUM(利润)*100.0/SUM(销售额) FROM orders"),
    ("淘宝渠道的利润率是多少", "scalar",
     "SELECT SUM(利润)*100.0/SUM(销售额) FROM orders WHERE 销售渠道='淘宝'"),
    ("音频设备类别的毛利率是多少", "scalar",
     "SELECT SUM(o.利润)*100.0/SUM(o.销售额) FROM orders o JOIN products p "
     "ON o.产品ID=p.产品ID WHERE p.产品类别='音频设备'"),
    ("手机配件占整体销售额的比例是多少", "scalar",
     "SELECT SUM(o.销售额)*100.0/(SELECT SUM(销售额) FROM orders) FROM orders o "
     "JOIN products p ON o.产品ID=p.产品ID WHERE p.产品类别='手机配件'"),
    ("2026年5月淘宝的销售额是多少", "scalar",
     "SELECT SUM(销售额) FROM orders WHERE 订单日期 LIKE '2026-05%' AND 销售渠道='淘宝'"),
    ("2026年12月京东的订单数是多少", "scalar",
     "SELECT COUNT(*) FROM orders WHERE 订单日期 LIKE '2026-12%' AND 销售渠道='京东'"),
    ("上海的订单数是多少", "scalar", "SELECT COUNT(*) FROM orders WHERE 客户城市='上海'"),
    ("深圳的销售额是多少", "scalar", "SELECT SUM(销售额) FROM orders WHERE 客户城市='深圳'"),
    ("拼多多渠道的销量是多少", "scalar",
     "SELECT SUM(销量) FROM orders WHERE 销售渠道='拼多多'"),
    ("降噪耳机的销售额是多少", "scalar",
     "SELECT SUM(o.销售额) FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "WHERE p.产品名称='降噪耳机'"),
    ("每个产品的销售额分别是多少", "row_count",
     "SELECT p.产品名称, SUM(o.销售额) FROM orders o JOIN products p ON o.产品ID=p.产品ID GROUP BY p.产品名称"),
    ("2026年第四季度的销售额是多少", "scalar",
     "SELECT SUM(销售额) FROM orders WHERE 订单日期 >= '2026-10-01' AND 订单日期 <= '2026-12-31'"),
]


def reference(conn: sqlite3.Connection, sql: str, kind: str):
    rows = conn.execute(sql).fetchall()
    if kind == "scalar":
        return float(rows[0][0]) if rows and rows[0][0] is not None else 0.0
    if kind == "row_count":
        return float(len(rows))
    if kind == "top_name":
        return str(rows[0][0]) if rows else ""
    if kind == "top3_names":
        return [str(r[0]) for r in rows[:3]]
    raise ValueError(kind)


def check(kind, expected, rows):
    if not rows:
        return False, "无结果行"
    flat = [v for row in rows for v in row]
    if kind == "scalar":
        nums = []
        for v in flat:
            if v is None or isinstance(v, bool):
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
    from app.datasource.sqlite import SQLiteDataSource

    ds = SQLiteDataSource(db_path=str(DB))
    await ds.connect()
    from app.services.schema import describe_schema

    schema = await describe_schema(ds)
    schema_text = json.dumps(schema, ensure_ascii=False)

    conn = sqlite3.connect(DB)
    refs = {q: reference(conn, sql, kind) for q, kind, sql in CASES}

    rows_out = []
    per_case = {q: [] for q, _, _ in CASES}
    run_rate = []
    for run_idx in range(args.repeat):
        hits = 0
        for question, kind, _sql in CASES:
            state = {"user_input": question, "datasource_schemas": [schema_text], "intent": "{}"}
            t0 = time.perf_counter()
            out = await generate_query(state)
            gen_ms = (time.perf_counter() - t0) * 1000
            sql = out.get("generated_sql", "")

            ok_exec, err, exec_ms, rows = False, "", 0.0, []
            if sql:
                try:
                    t1 = time.perf_counter()
                    res = await ds.execute_query(sql)
                    exec_ms = (time.perf_counter() - t1) * 1000
                    ok_exec, rows = True, res.rows
                except Exception as exc:  # noqa: BLE001
                    err = f"执行失败: {exc}"
            else:
                err = out.get("error", "未生成 SQL")

            ok, detail = (False, err) if not ok_exec else check(kind, refs[question], rows)
            per_case[question].append((ok_exec, ok, detail, sql, gen_ms, exec_ms))
            hits += ok
            if args.verbose:
                print(f'[{"OK " if ok else "MISS"}] {question} | {detail}')
        run_rate.append(round(hits / len(CASES), 4))

    await ds.disconnect()
    conn.close()

    for question, kind, _sql in CASES:
        results = per_case[question]
        n_ok = sum(1 for _, ok, *_ in results if ok)
        rows_out.append({
            "q": question,
            "kind": kind,
            "sql": results[-1][3],
            "exec_ok": any(r[0] for r in results),
            "correct": n_ok * 2 > len(results),
            "detail": results[-1][2],
            "gen_ms": round(sum(r[4] for r in results) / len(results), 1),
            "exec_ms": round(sum(r[5] for r in results) / len(results), 1),
        })

    n = len(rows_out)
    summary = {
        "dataset": DB.name,
        "rows": 30000,
        "tables": 2,
        "cases": n,
        "correct_rate": round(sum(r["correct"] for r in rows_out) / n, 4),
        "exec_rate": round(sum(r["exec_ok"] for r in rows_out) / n, 4),
        "avg_gen_ms": round(sum(r["gen_ms"] for r in rows_out) / n, 1),
        "avg_exec_ms": round(sum(r["exec_ms"] for r in rows_out) / n, 1),
        "temperature": args.temperature,
        "misses": [{"q": r["q"], "detail": r["detail"], "sql": r["sql"]}
                   for r in rows_out if not r["correct"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_path = args.output or OUT_DIR / "text2sql_scale.result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "rows": rows_out}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[saved] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
