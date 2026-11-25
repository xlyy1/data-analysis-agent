"""演示数据生成器（确定性）。

生成一套"中小工厂/电商"口径的样例数据：
- 事实表 `订单明细`：2026-01 ~ 2026-10，4 城市 × 3 渠道 × 5 产品，约 1200 行
- 维度表 `产品`、`客户`
- 以及一份"脏"的 CSV（列名带空格、整行空行、完全重复行、前导零编码），
  用来演示上传清洗链路。

同一个 seed 生成的数值完全一致，因此可以写进 benchmark / 截图，不会每次跑不一样。
"""

from __future__ import annotations

import csv
import os
import random
import sqlite3
from datetime import date
from pathlib import Path

SEED = 20260101

CITIES = ["杭州", "苏州", "宁波", "上海"]
CHANNELS = ["线上", "线下", "批发"]
MEMBERS = ["黄金", "白银", "普通"]

PRODUCTS = [
    # code, name, category, unit_cost, list_price
    ("P001", "折叠收纳箱", "家居", 28.0, 69.0),
    ("P002", "不锈钢保温杯", "厨具", 35.0, 89.0),
    ("P003", "棉麻四件套", "家纺", 120.0, 259.0),
    ("P004", "露营折叠椅", "户外", 55.0, 139.0),
    ("P005", "电动研磨咖啡机", "小家电", 210.0, 269.0),  # 刻意定成高成本低毛利
]

CUSTOMERS = [
    (f"C{i:03d}", f"客户{i:03d}", MEMBERS[i % 3], CITIES[i % 4])
    for i in range(1, 121)
]


def _orders(start: date, months: int, rng: random.Random) -> list[tuple]:
    rows: list[tuple] = []
    sequence = 0
    for month in range(months):
        year = start.year + (start.month - 1 + month) // 12
        month_num = (start.month - 1 + month) % 12 + 1
        for _ in range(120):
            sequence += 1
            day = rng.randint(1, 28)
            order_date = date(year, month_num, day)
            product = rng.choice(PRODUCTS)
            code, _name, category, unit_cost, price = product
            city = rng.choice(CITIES)
            channel = rng.choice(CHANNELS)
            customer = rng.choice(CUSTOMERS)
            qty = rng.choice([1, 1, 2, 2, 3, 5, 8, 12])
            # 渠道折扣 + 月度季节性 + 随机扰动
            discount = {"线上": 0.95, "线下": 1.0, "批发": 0.82}[channel]
            seasonal = 1.0 + (0.18 if month_num in (9, 10) else 0.0)
            unit_price = round(price * discount * seasonal * rng.uniform(0.96, 1.04), 2)
            revenue = round(unit_price * qty, 2)
            # 批发渠道的咖啡机成本倒挂 → 制造一个真实可诊断的亏损点
            cost_factor = 1.0
            if code == "P005" and channel == "批发":
                cost_factor = 1.12
            cost = round(unit_cost * qty * cost_factor * rng.uniform(0.98, 1.02), 2)
            profit = round(revenue - cost, 2)
            rows.append(
                (
                    f"SO{year}{month_num:02d}{sequence:05d}",
                    order_date.isoformat(),
                    customer[0],
                    code,
                    city,
                    channel,
                    qty,
                    unit_price,
                    revenue,
                    cost,
                    profit,
                    category,
                )
            )
    return rows


ORDER_COLUMNS = [
    ("订单号", "TEXT PRIMARY KEY"),
    ("订单日期", "TEXT"),
    ("客户编号", "TEXT"),
    ("产品编号", "TEXT"),
    ("城市", "TEXT"),
    ("渠道", "TEXT"),
    ("数量", "INTEGER"),
    ("单价", "REAL"),
    ("销售额", "REAL"),
    ("成本", "REAL"),
    ("利润", "REAL"),
    ("品类", "TEXT"),
]


def build_sqlite(path: Path, *, months: int = 10, start: date | None = None) -> dict:
    rng = random.Random(SEED)
    start = start or date(2026, 1, 1)
    orders = _orders(start, months, rng)

    path.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再原子替换：写到一半被中断不会留下"有表没数据"的半成品库
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute(
            "CREATE TABLE 订单明细 ("
            + ", ".join(f'"{name}" {dtype}' for name, dtype in ORDER_COLUMNS)
            + ")"
        )
        conn.executemany(
            "INSERT INTO 订单明细 VALUES ("
            + ",".join("?" * len(ORDER_COLUMNS))
            + ")",
            orders,
        )
        conn.execute(
            "CREATE TABLE 产品 (产品编号 TEXT PRIMARY KEY, 产品名称 TEXT, 品类 TEXT, 单位成本 REAL, 标准售价 REAL)"
        )
        conn.executemany("INSERT INTO 产品 VALUES (?,?,?,?,?)", PRODUCTS)
        conn.execute(
            "CREATE TABLE 客户 (客户编号 TEXT PRIMARY KEY, 客户名称 TEXT, 会员等级 TEXT, 城市 TEXT)"
        )
        conn.executemany("INSERT INTO 客户 VALUES (?,?,?,?)", CUSTOMERS)
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM 订单明细").fetchone()[0]
        if total <= 0:  # 防御：空库绝不能当成功
            raise RuntimeError("样例数据生成后行数为 0")
    finally:
        conn.close()
    os.replace(tmp_path, path)
    return {"db_path": str(path), "orders": total, "products": len(PRODUCTS), "customers": len(CUSTOMERS)}


def build_messy_csv(path: Path) -> dict:
    """生成一份需要清洗的 CSV：脏列名 + 空行 + 重复行 + 前导零 + 首尾空格。"""
    rng = random.Random(SEED + 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[list[str]] = []
    header = [" 门店编号 ", "门店名称", "", "城市", "月份", "销售额 ", "客流"]
    for index in range(60):
        rows.append(
            [
                f"0{rng.randint(1, 12):02d}",  # 前导零，必须保持文本
                f"  {CITIES[index % 4]}旗舰店  ",
                "运营一部",
                CITIES[index % 4],
                f"2026-{rng.randint(1, 10):02d}",
                f"{rng.uniform(20000, 180000):.2f} ",
                str(rng.randint(200, 3000)),
            ]
        )
    # 完全重复的两行 + 一整行空行
    rows.append(list(rows[0]))
    rows.append(list(rows[1]))
    rows.append(["", "", "", "", "", "", ""])

    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(header)
        writer.writerows(rows)
    return {"csv_path": str(path), "rows": len(rows)}


def build_all(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    db = build_sqlite(out_dir / "shop.db")
    messy = build_messy_csv(out_dir / "门店经营明细_待清洗.csv")
    return {**db, **messy}


if __name__ == "__main__":  # pragma: no cover - 手工生成用
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/samples")
    print(build_all(target))
