"""留出集 2：图书馆借阅（修复 sample_values 后的独立验证，只跑一次）。

运行：
    python backend/tests/evaluate_text2sql_holdout2.py --temperature 0
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
DB = BACKEND / "data" / "holdout_library.db"
OUT_DIR = BACKEND / "tests" / "data"

sys.path.insert(0, str(BACKEND))

CASES = [
    ("一共有多少条借阅记录", "scalar", "SELECT COUNT(*) FROM loans"),
    ("2026年3月有多少条借阅记录", "scalar",
     "SELECT COUNT(*) FROM loans WHERE 借阅日期 LIKE '2026-03%'"),
    ("逾期总天数是多少", "scalar", "SELECT SUM(逾期天数) FROM loans"),
    ("逾期记录有多少条", "scalar", "SELECT COUNT(*) FROM loans WHERE 逾期天数 > 0"),
    ("平均逾期天数是多少", "scalar", "SELECT AVG(逾期天数) FROM loans"),
    ("每月分别有多少条借阅记录", "row_count",
     "SELECT substr(借阅日期,1,7), COUNT(*) FROM loans GROUP BY 1"),
    ("各读者类型的借阅记录数是多少", "row_count",
     "SELECT 读者类型, COUNT(*) FROM loans GROUP BY 读者类型"),
    ("各分馆的逾期总天数是多少", "row_count",
     "SELECT 分馆, SUM(逾期天数) FROM loans GROUP BY 分馆"),
    ("各图书类别的借阅次数是多少", "row_count",
     "SELECT b.类别, COUNT(*) FROM loans l JOIN books b ON l.图书编号=b.图书编号 GROUP BY b.类别"),
    ("借阅次数最多的书是哪个", "top_name",
     "SELECT b.书名 FROM loans l JOIN books b ON l.图书编号=b.图书编号 "
     "GROUP BY b.书名 ORDER BY COUNT(*) DESC LIMIT 1"),
    ("逾期总天数最多的分馆是哪个", "top_name",
     "SELECT 分馆 FROM loans GROUP BY 分馆 ORDER BY SUM(逾期天数) DESC LIMIT 1"),
    ("借阅次数最少的类别是哪个", "top_name",
     "SELECT b.类别 FROM loans l JOIN books b ON l.图书编号=b.图书编号 "
     "GROUP BY b.类别 ORDER BY COUNT(*) ASC LIMIT 1"),
    ("教师借阅了多少条记录", "scalar", "SELECT COUNT(*) FROM loans WHERE 读者类型='教师'"),
    ("校外读者的逾期总天数是多少", "scalar",
     "SELECT SUM(逾期天数) FROM loans WHERE 读者类型='校外'"),
    ("东区分馆的借阅记录数是多少", "scalar",
     "SELECT COUNT(*) FROM loans WHERE 分馆='东区分馆'"),
    ("计算机类图书的借阅次数是多少", "scalar",
     "SELECT COUNT(*) FROM loans l JOIN books b ON l.图书编号=b.图书编号 WHERE b.类别='计算机'"),
    ("《人类简史》被借阅了多少次", "scalar",
     "SELECT COUNT(*) FROM loans l JOIN books b ON l.图书编号=b.图书编号 WHERE b.书名='人类简史'"),
    ("2026年5月学生读者的借阅记录数是多少", "scalar",
     "SELECT COUNT(*) FROM loans WHERE 借阅日期 LIKE '2026-05%' AND 读者类型='学生'"),
    ("各读者类型的逾期率分别是多少", "row_count",
     "SELECT 读者类型, 1.0*SUM(CASE WHEN 逾期天数>0 THEN 1 ELSE 0 END)/COUNT(*) FROM loans GROUP BY 读者类型"),
    ("整体逾期率是多少", "scalar",
     "SELECT SUM(CASE WHEN 逾期天数>0 THEN 1 ELSE 0 END)*100.0/COUNT(*) FROM loans"),
    ("借阅次数前三的书", "top3_names",
     "SELECT b.书名 FROM loans l JOIN books b ON l.图书编号=b.图书编号 "
     "GROUP BY b.书名 ORDER BY COUNT(*) DESC LIMIT 3"),
    ("总馆占整体借阅记录的比例是多少", "scalar",
     "SELECT (SELECT COUNT(*) FROM loans WHERE 分馆='总馆')*100.0/COUNT(*) FROM loans"),
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
    from app.services.schema import describe_schema

    ds = SQLiteDataSource(db_path=str(DB))
    await ds.connect()
    schema = await describe_schema(ds)
    schema_text = json.dumps(schema, ensure_ascii=False)

    conn = sqlite3.connect(DB)
    refs = {q: reference(conn, sql, kind) for q, kind, sql in CASES}

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
        "holdout": True,
        "note": "第三套数据，修复 sample_values 后只跑一次",
        "cases": n,
        "correct_rate": round(hits / n, 4),
        "exec_rate": round(sum(r["exec_ok"] for r in rows_out) / n, 4),
        "avg_gen_ms": round(sum(r["gen_ms"] for r in rows_out) / n, 1),
        "avg_exec_ms": round(sum(r["exec_ms"] for r in rows_out) / n, 1),
        "misses": [{"q": r["q"], "detail": r["detail"], "sql": r["sql"]}
                   for r in rows_out if not r["correct"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_path = args.output or OUT_DIR / "text2sql_holdout2.result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "rows": rows_out}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[saved] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
