"""第三套数据（图书馆借阅），用于验证 sample_values 修复后的泛化。

与前面两套都不同域、不同列名。
用法：python tools/gen_holdout2_dataset.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from app.core.sqlite import sqlite_connection

OUT = Path(__file__).resolve().parents[1] / "data" / "holdout_library.db"
LOANS = 6_000
SEED = 314159

BOOKS = [
    ("B01", "算法导论", "计算机", 128),
    ("B02", "数据库系统概念", "计算机", 99),
    ("B03", "深入理解计算机系统", "计算机", 139),
    ("B04", "国富论", "经济", 68),
    ("B05", "经济学原理", "经济", 88),
    ("B06", "人类简史", "历史", 59),
    ("B07", "万历十五年", "历史", 45),
    ("B08", "高等数学", "教材", 56),
    ("B09", "线性代数", "教材", 42),
    ("B10", "夜航西飞", "文学", 38),
]
READERS = ["学生", "教师", "校外"]
BRANCHES = ["总馆", "东区分馆", "南区分馆"]


def main() -> None:
    rng = np.random.default_rng(SEED)
    books = pd.DataFrame(BOOKS, columns=["图书编号", "书名", "类别", "定价"])

    days = pd.date_range("2026-01-01", "2026-09-30", freq="D")
    loans = pd.DataFrame({
        "借阅编号": np.arange(1, LOANS + 1),
        "借阅日期": pd.to_datetime(rng.choice(days, size=LOANS)).strftime("%Y-%m-%d"),
        "图书编号": rng.choice(books["图书编号"].to_numpy(), size=LOANS),
        "读者类型": rng.choice(READERS, size=LOANS, p=[0.68, 0.22, 0.10]),
        "分馆": rng.choice(BRANCHES, size=LOANS, p=[0.55, 0.25, 0.20]),
        "逾期天数": rng.choice([0, 0, 0, 0, 0, 3, 7, 15, 30], size=LOANS),
    })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    with sqlite_connection(OUT) as conn:
        loans.to_sql("loans", conn, index=False)
        books.to_sql("books", conn, index=False)
        conn.execute("CREATE INDEX idx_loans_book ON loans(图书编号)")

    print(f"写入 {OUT}")
    print(f"loans: {len(loans)} 行 | books: {len(books)} 行")
    print(f"逾期总天数: {loans['逾期天数'].sum():,.0f} | 逾期记录: {(loans['逾期天数'] > 0).sum():,}")


if __name__ == "__main__":
    main()
