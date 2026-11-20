"""多表 JOIN 与子查询评测：4 表 5 万行仓库数据。

覆盖：三表/四表 JOIN、EXISTS / NOT EXISTS、标量子查询、IN 子查询、HAVING。
运行：
    python backend/tests/evaluate_text2sql_join.py --temperature 0
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
DB = BACKEND / "data" / "warehouse.db"
OUT_DIR = BACKEND / "tests" / "data"

sys.path.insert(0, str(BACKEND))

J = "orders o JOIN products p ON o.产品ID=p.产品ID"
JC = "orders o JOIN customers c ON o.客户ID=c.客户ID"

CASES = [
    # --- 两表 JOIN ---
    ("各产品类别的销售额是多少", "row_count",
     f"SELECT p.产品类别, SUM(o.金额) FROM {J} GROUP BY p.产品类别"),
    ("各城市的订单数是多少", "row_count",
     f"SELECT c.城市, COUNT(*) FROM {JC} GROUP BY c.城市"),
    ("各客户等级的消费金额是多少", "row_count",
     f"SELECT c.等级, SUM(o.金额) FROM {JC} GROUP BY c.等级"),
    ("销售额最高的产品类别是哪个", "top_name",
     f"SELECT p.产品类别 FROM {J} GROUP BY p.产品类别 ORDER BY SUM(o.金额) DESC LIMIT 1"),
    ("订单数最少的城市是哪个", "top_name",
     f"SELECT c.城市 FROM {JC} GROUP BY c.城市 ORDER BY COUNT(*) ASC LIMIT 1"),
    ("黄金客户的消费金额是多少", "scalar",
     f"SELECT SUM(o.金额) FROM {JC} WHERE c.等级='黄金'"),
    ("上海客户的订单数是多少", "scalar",
     f"SELECT COUNT(*) FROM {JC} WHERE c.城市='上海'"),
    ("音频设备类别的销量是多少", "scalar",
     f"SELECT SUM(o.数量) FROM {J} WHERE p.产品类别='音频设备'"),
    # --- 三表 JOIN（订单 + 产品 + 供应商）---
    ("各供应商的销售额是多少", "row_count",
     f"SELECT s.供应商名称, SUM(o.金额) FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "GROUP BY s.供应商名称"),
    ("各供应商的订单数是多少", "row_count",
     f"SELECT s.供应商名称, COUNT(*) FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "GROUP BY s.供应商名称"),
    ("销售额最高的供应商是哪个", "top_name",
     f"SELECT s.供应商名称 FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "GROUP BY s.供应商名称 ORDER BY SUM(o.金额) DESC LIMIT 1"),
    ("华东地区供应商的销售额是多少", "scalar",
     f"SELECT SUM(o.金额) FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "WHERE s.所在地区='华东'"),
    ("海外供应商的订单数是多少", "scalar",
     f"SELECT COUNT(*) FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "WHERE s.所在地区='海外'"),
    # --- 四表 JOIN（订单 + 客户 + 产品 + 供应商）---
    ("各城市的黄金客户贡献了多少销售额", "row_count",
     f"SELECT c.城市, SUM(o.金额) FROM {JC} WHERE c.等级='黄金' GROUP BY c.城市"),
    ("华东供应商卖到上海客户的金额是多少", "scalar",
     f"SELECT SUM(o.金额) FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "JOIN suppliers s ON p.供应商ID=s.供应商ID JOIN customers c ON o.客户ID=c.客户ID "
     "WHERE s.所在地区='华东' AND c.城市='上海'"),
    ("华南地区供应商在音频设备上的销售额是多少", "scalar",
     f"SELECT SUM(o.金额) FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "WHERE s.所在地区='华南' AND p.产品类别='音频设备'"),
    # --- 标量子查询 ---
    ("金额高于平均订单金额的订单有多少笔", "scalar",
     "SELECT COUNT(*) FROM orders WHERE 金额 > (SELECT AVG(金额) FROM orders)"),
    ("利润最高的那笔订单来自哪个城市", "top_name",
     "SELECT c.城市 FROM orders o JOIN customers c ON o.客户ID=c.客户ID "
     "ORDER BY o.利润 DESC LIMIT 1"),
    ("消费金额最高的客户来自哪个城市", "top_name",
     "SELECT c.城市 FROM orders o JOIN customers c ON o.客户ID=c.客户ID "
     "GROUP BY c.客户ID ORDER BY SUM(o.金额) DESC LIMIT 1"),
    ("订单金额高于该客户平均订单金额的订单数是多少", "scalar",
     "SELECT COUNT(*) FROM orders o WHERE o.金额 > "
     "(SELECT AVG(o2.金额) FROM orders o2 WHERE o2.客户ID=o.客户ID)"),
    # --- IN / EXISTS ---
    ("买过音频设备的客户数是多少", "scalar",
     f"SELECT COUNT(DISTINCT o.客户ID) FROM {J} WHERE p.产品类别='音频设备'"),
    ("从未下过订单的客户数是多少", "scalar",
     "SELECT COUNT(*) FROM customers c WHERE NOT EXISTS "
     "(SELECT 1 FROM orders o WHERE o.客户ID=c.客户ID)"),
    ("没有卖出去过的产品数是多少", "scalar",
     "SELECT COUNT(*) FROM products p WHERE NOT EXISTS "
     "(SELECT 1 FROM orders o WHERE o.产品ID=p.产品ID)"),
    ("买过充电宝的客户有多少", "scalar",
     f"SELECT COUNT(DISTINCT o.客户ID) FROM {J} WHERE p.产品名称='充电宝'"),
    ("供货的产品全部卖出去过的供应商有几家", "scalar",
     "SELECT COUNT(*) FROM suppliers s WHERE NOT EXISTS ("
     "SELECT 1 FROM products p WHERE p.供应商ID=s.供应商ID AND NOT EXISTS "
     "(SELECT 1 FROM orders o WHERE o.产品ID=p.产品ID))"),
    # --- HAVING ---
    ("订单数超过100笔的客户有多少", "scalar",
     "SELECT COUNT(*) FROM (SELECT 客户ID FROM orders GROUP BY 客户ID HAVING COUNT(*) > 100)"),
    ("消费金额超过5万元的客户有多少", "scalar",
     "SELECT COUNT(*) FROM (SELECT 客户ID FROM orders GROUP BY 客户ID HAVING SUM(金额) > 50000)"),
    ("订单数超过2000笔的产品有多少", "scalar",
     "SELECT COUNT(*) FROM (SELECT 产品ID FROM orders GROUP BY 产品ID HAVING COUNT(*) > 2000)"),
    ("销售额超过10万元的类别有多少", "scalar",
     "SELECT COUNT(*) FROM (SELECT p.产品类别 FROM orders o JOIN products p ON o.产品ID=p.产品ID "
     "GROUP BY p.产品类别 HAVING SUM(o.金额) > 100000)"),
    # --- JOIN + 时间 ---
    ("2026年3月音频设备的销售额是多少", "scalar",
     f"SELECT SUM(o.金额) FROM {J} WHERE o.订单日期 LIKE '2026-03%' AND p.产品类别='音频设备'"),
    ("2026年下半年华东供应商的订单数是多少", "scalar",
     f"SELECT COUNT(*) FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "WHERE o.订单日期 >= '2026-07-01' AND s.所在地区='华东'"),
    ("2026年11月黄金客户的消费金额是多少", "scalar",
     f"SELECT SUM(o.金额) FROM {JC} WHERE o.订单日期 LIKE '2026-11%' AND c.等级='黄金'"),
    ("每个月华东供应商的销售额是多少", "row_count",
     f"SELECT substr(o.订单日期,1,7), SUM(o.金额) FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "WHERE s.所在地区='华东' GROUP BY 1"),
    # --- 比率（多表）---
    ("整体利润率是多少", "scalar", "SELECT SUM(利润)*100.0/SUM(金额) FROM orders"),
    ("华东供应商的利润率是多少", "scalar",
     f"SELECT SUM(o.利润)*100.0/SUM(o.金额) FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "WHERE s.所在地区='华东'"),
    ("音频设备占整体销售额的比例是多少", "scalar",
     f"SELECT (SELECT SUM(o.金额) FROM {J} WHERE p.产品类别='音频设备')*100.0/"
     "(SELECT SUM(金额) FROM orders)"),
    ("黄金客户的消费金额占比是多少", "scalar",
     f"SELECT (SELECT SUM(o.金额) FROM {JC} WHERE c.等级='黄金')*100.0/"
     "(SELECT SUM(金额) FROM orders)"),
    # --- 排序与 TopN（多表）---
    ("销售额前三的供应商", "top3_names",
     f"SELECT s.供应商名称 FROM {J} JOIN suppliers s ON p.供应商ID=s.供应商ID "
     "GROUP BY s.供应商名称 ORDER BY SUM(o.金额) DESC LIMIT 3"),
    ("销售额前三的类别", "top3_names",
     f"SELECT p.产品类别 FROM {J} GROUP BY p.产品类别 ORDER BY SUM(o.金额) DESC LIMIT 3"),
    ("订单数最多的城市", "top_name",
     f"SELECT c.城市 FROM {JC} GROUP BY c.城市 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("平均订单金额最高的客户等级是哪个", "top_name",
     "SELECT 等级 FROM (SELECT c.等级, AVG(o.金额) a FROM orders o JOIN customers c "
     "ON o.客户ID=c.客户ID GROUP BY c.等级) ORDER BY a DESC LIMIT 1"),
]


def reference(conn, sql, kind):
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
            # SUM over an empty set returns NULL；期望 0 时应视为一致
            if expected == 0 and len(rows) == 1 and len(flat) == 1 and flat[0] is None:
                return True, "结果为 NULL，与期望 0 一致"
            return False, "结果中没有数值"
        got = max(nums, key=abs)
        tol = max(abs(expected) * 0.01, 0.5)
        return abs(got - expected) <= tol, f"期望≈{expected:.2f} 实得≈{got:.2f}"
    if kind == "top_name":
        # 模型可能多返回几列（如 ID、金额、城市），答案不一定在第一列
        cells = [str(v) for v in rows[0] if v is not None]
        hit = any(expected in cell or cell in str(expected) for cell in cells)
        return hit, f"期望包含「{expected}」实得{cells}"
    if kind == "top3_names":
        got = [str(r[0]) for r in rows[:3]]
        return len(set(expected) & set(got)) >= 2, f"期望前三{expected} 实得{got}"
    if kind == "row_count":
        return abs(len(rows) - expected) <= 1, f"期望{int(expected)}行 实得{len(rows)}行"
    return False, "未知检查类型"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    os.environ["LLM_TEMPERATURE"] = str(args.temperature)

    from app.agent.nodes.query import generate_query
    from app.datasource.sqlite import SQLiteDataSource
    from app.services.schema import describe_schema

    ds = SQLiteDataSource(db_path=str(DB))
    await ds.connect()
    schema = await describe_schema(ds)
    schema_text = json.dumps(schema, ensure_ascii=False)
    await ds.disconnect()

    conn = sqlite3.connect(DB)
    refs = {q: reference(conn, sql, kind) for q, kind, sql in CASES}

    await ds.connect()
    rows_out, hits = [], 0
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
        hits += ok
        if args.verbose:
            print(f'[{"OK " if ok else "MISS"}] {question} | {detail}')
        rows_out.append({"q": question, "kind": kind, "sql": sql, "exec_ok": ok_exec,
                         "correct": ok, "detail": detail,
                         "gen_ms": round(gen_ms, 1), "exec_ms": round(exec_ms, 1)})

    await ds.disconnect()
    conn.close()

    n = len(rows_out)
    summary = {
        "dataset": DB.name,
        "rows": 50000,
        "tables": 4,
        "cases": n,
        "correct_rate": round(hits / n, 4),
        "exec_rate": round(sum(r["exec_ok"] for r in rows_out) / n, 4),
        "avg_gen_ms": round(sum(r["gen_ms"] for r in rows_out) / n, 1),
        "avg_exec_ms": round(sum(r["exec_ms"] for r in rows_out) / n, 1),
        "misses": [{"q": r["q"], "detail": r["detail"], "sql": r["sql"]}
                   for r in rows_out if not r["correct"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_path = args.output or OUT_DIR / "text2sql_join.result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "rows": rows_out}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[saved] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
