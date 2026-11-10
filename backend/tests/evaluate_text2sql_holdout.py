"""留出集评测：未参与提示词调整的门店客流数据，只跑一次。

运行（一次性，跑完不得再据此调提示词）：
    python backend/tests/evaluate_text2sql_holdout.py --temperature 0
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
DB = BACKEND / "data" / "holdout_visits.db"
OUT_DIR = BACKEND / "tests" / "data"

sys.path.insert(0, str(BACKEND))

CASES = [
    ("一共多少笔到店记录", "scalar", "SELECT COUNT(*) FROM visits"),
    ("消费金额合计是多少", "scalar", "SELECT SUM(消费金额) FROM visits"),
    ("实付金额合计是多少", "scalar", "SELECT SUM(实付金额) FROM visits"),
    ("折扣金额合计是多少", "scalar", "SELECT SUM(折扣金额) FROM visits"),
    ("平均消费金额是多少", "scalar", "SELECT AVG(消费金额) FROM visits"),
    ("2026年5月的消费金额是多少", "scalar",
     "SELECT SUM(消费金额) FROM visits WHERE 到店时间 LIKE '2026-05%'"),
    ("2026年8月有多少笔到店记录", "scalar",
     "SELECT COUNT(*) FROM visits WHERE 到店时间 LIKE '2026-08%'"),
    ("每月分别多少笔到店记录", "row_count",
     "SELECT substr(到店时间,1,7), COUNT(*) FROM visits GROUP BY 1"),
    ("各会员等级的消费金额是多少", "row_count",
     "SELECT 会员等级, SUM(消费金额) FROM visits GROUP BY 会员等级"),
    ("各城市的到店记录数是多少", "row_count",
     "SELECT s.城市, COUNT(*) FROM visits v JOIN stores s ON v.门店编码=s.门店编码 GROUP BY s.城市"),
    ("各区域的实付金额是多少", "row_count",
     "SELECT s.区域, SUM(v.实付金额) FROM visits v JOIN stores s ON v.门店编码=s.门店编码 GROUP BY s.区域"),
    ("消费金额最高的门店是哪个", "top_name",
     "SELECT s.门店名称 FROM visits v JOIN stores s ON v.门店编码=s.门店编码 "
     "GROUP BY s.门店名称 ORDER BY SUM(v.消费金额) DESC LIMIT 1"),
    ("到店记录最少的城市是哪个", "top_name",
     "SELECT s.城市 FROM visits v JOIN stores s ON v.门店编码=s.门店编码 "
     "GROUP BY s.城市 ORDER BY COUNT(*) ASC LIMIT 1"),
    ("实付金额最高的会员等级是哪个", "top_name",
     "SELECT 会员等级 FROM visits GROUP BY 会员等级 ORDER BY SUM(实付金额) DESC LIMIT 1"),
    ("整体折扣率是多少", "scalar", "SELECT SUM(折扣金额)*100.0/SUM(消费金额) FROM visits"),
    ("钻石会员的折扣率是多少", "scalar",
     "SELECT SUM(折扣金额)*100.0/SUM(消费金额) FROM visits WHERE 会员等级='钻石'"),
    ("华东区域占整体消费金额的比例是多少", "scalar",
     "SELECT (SELECT SUM(v.消费金额) FROM visits v JOIN stores s ON v.门店编码=s.门店编码 "
     "WHERE s.区域='华东')*100.0/(SELECT SUM(消费金额) FROM visits)"),
    ("上海的门店数量是多少", "scalar", "SELECT COUNT(*) FROM stores WHERE 城市='上海'"),
    ("深圳的实付金额是多少", "scalar",
     "SELECT SUM(v.实付金额) FROM visits v JOIN stores s ON v.门店编码=s.门店编码 WHERE s.城市='深圳'"),
    ("黄金会员有多少笔到店记录", "scalar",
     "SELECT COUNT(*) FROM visits WHERE 会员等级='黄金'"),
    ("2026年4月华南区域的消费金额是多少", "scalar",
     "SELECT SUM(v.消费金额) FROM visits v JOIN stores s ON v.门店编码=s.门店编码 "
     "WHERE v.到店时间 LIKE '2026-04%' AND s.区域='华南'"),
    ("各门店的平均消费金额是多少", "row_count",
     "SELECT 门店编码, AVG(消费金额) FROM visits GROUP BY 门店编码"),
    ("消费金额前三的门店", "top3_names",
     "SELECT s.门店名称 FROM visits v JOIN stores s ON v.门店编码=s.门店编码 "
     "GROUP BY s.门店名称 ORDER BY SUM(v.消费金额) DESC LIMIT 3"),
    ("2026年第二季度的消费金额是多少", "scalar",
     "SELECT SUM(消费金额) FROM visits WHERE 到店时间 >= '2026-04-01' AND 到店时间 <= '2026-06-30'"),
    ("普通会员的实付金额是多少", "scalar",
     "SELECT SUM(实付金额) FROM visits WHERE 会员等级='普通'"),
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
            return False, "结果中没有数值"
        got = max(nums, key=abs)
        tol = max(abs(expected) * 0.01, 0.5)
        return abs(got - expected) <= tol, f"期望≈{expected:.2f} 实得≈{got:.2f}"
    if kind == "top_name":
        got = str(rows[0][0])
        return expected in got or got in str(expected), f"期望包含「{expected}」实得「{got}」"
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

    ds = SQLiteDataSource(db_path=str(DB))
    await ds.connect()
    from app.services.schema import describe_schema

    schema = await describe_schema(ds)
    schema_text = json.dumps(schema, ensure_ascii=False)

    conn = sqlite3.connect(DB)
    refs = {q: reference(conn, sql, kind) for q, kind, sql in CASES}

    rows_out = []
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
        "holdout": True,
        "note": "未参与任何提示词调整，只跑一次",
        "cases": n,
        "correct_rate": round(hits / n, 4),
        "exec_rate": round(sum(r["exec_ok"] for r in rows_out) / n, 4),
        "avg_gen_ms": round(sum(r["gen_ms"] for r in rows_out) / n, 1),
        "avg_exec_ms": round(sum(r["exec_ms"] for r in rows_out) / n, 1),
        "misses": [{"q": r["q"], "detail": r["detail"], "sql": r["sql"]}
                   for r in rows_out if not r["correct"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_path = args.output or OUT_DIR / "text2sql_holdout.result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "rows": rows_out}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[saved] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
