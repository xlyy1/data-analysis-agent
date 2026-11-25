"""生成 4 表 5 万行的评测数据：客户 / 产品 / 供应商 / 订单。

用于验证多表 JOIN 与子查询场景。
用法：python tools/gen_warehouse_dataset.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from app.core.sqlite import sqlite_connection

OUT = Path(__file__).resolve().parents[1] / "data" / "warehouse.db"
ORDERS = 50_000
SEED = 20261111

SUPPLIERS = [
    ("SUP01", "华东电子", "华东"),
    ("SUP02", "华南数码", "华南"),
    ("SUP03", "华北科技", "华北"),
    ("SUP04", "西南智造", "西南"),
    ("SUP05", "海外进口", "海外"),
    ("SUP06", "华东智配", "华东"),
]

CATEGORIES = {
    "手机配件": ["充电宝", "数据线", "手机壳", "钢化膜"],
    "电脑外设": ["无线鼠标", "机械键盘", "扩展坞", "显示器支架"],
    "穿戴设备": ["智能手环", "智能手表"],
    "音频设备": ["运动耳机", "蓝牙音箱", "降噪耳机"],
}
CITIES = ["上海", "北京", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "苏州"]
LEVELS = ["普通", "白银", "黄金"]


def main() -> None:
    rng = np.random.default_rng(SEED)

    suppliers = pd.DataFrame(SUPPLIERS, columns=["供应商ID", "供应商名称", "所在地区"])

    products = []
    pid = 1
    for category, names in CATEGORIES.items():
        for name in names:
            price = float(rng.integers(30, 1000))
            cost_ratio = float(rng.uniform(0.45, 0.75))
            products.append((
                f"P{pid:03d}", name, category,
                round(price, 2), round(price * cost_ratio, 2),
                str(rng.choice(suppliers["供应商ID"].to_numpy())),
            ))
            pid += 1
    products = pd.DataFrame(products, columns=["产品ID", "产品名称", "产品类别", "售价", "成本价", "供应商ID"])

    customers = pd.DataFrame({
        "客户ID": [f"C{i:04d}" for i in range(1, 501)],
        "客户名称": [f"客户{i:04d}" for i in range(1, 501)],
        "城市": rng.choice(CITIES, size=500),
        "等级": rng.choice(LEVELS, size=500, p=[0.6, 0.3, 0.1]),
        "注册日期": pd.to_datetime(rng.choice(
            pd.date_range("2025-01-01", "2026-06-30", freq="D"), size=500)).strftime("%Y-%m-%d"),
    })

    days = pd.date_range("2026-01-01", "2026-12-31", freq="D")
    month_weight = np.where(pd.Series(days).dt.month.isin([6, 11, 12]), 2.0, 1.0)
    order_dates = rng.choice(days, size=ORDERS, p=month_weight / month_weight.sum())

    orders = pd.DataFrame({
        "订单ID": np.arange(1, ORDERS + 1),
        "订单日期": pd.to_datetime(order_dates).strftime("%Y-%m-%d"),
        "客户ID": rng.choice(customers["客户ID"].to_numpy(), size=ORDERS),
        "产品ID": rng.choice(products["产品ID"].to_numpy(), size=ORDERS),
        "数量": rng.integers(1, 11, size=ORDERS),
    })
    merged = orders.merge(products, on="产品ID", how="left")
    merged["金额"] = (merged["数量"] * merged["售价"]).round(2)
    merged["成本"] = (merged["数量"] * merged["成本价"]).round(2)
    merged["利润"] = (merged["金额"] - merged["成本"]).round(2)
    orders_out = merged[["订单ID", "订单日期", "客户ID", "产品ID", "数量", "金额", "成本", "利润"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    with sqlite_connection(OUT) as conn:
        orders_out.to_sql("orders", conn, index=False)
        customers.to_sql("customers", conn, index=False)
        products.to_sql("products", conn, index=False)
        suppliers.to_sql("suppliers", conn, index=False)
        conn.execute("CREATE INDEX idx_orders_customer ON orders(客户ID)")
        conn.execute("CREATE INDEX idx_orders_product ON orders(产品ID)")
        conn.execute("CREATE INDEX idx_orders_date ON orders(订单日期)")

    print(f"写入 {OUT}")
    print(f"orders {len(orders_out)} | customers {len(customers)} | products {len(products)} | suppliers {len(suppliers)}")
    print(f"金额合计 {orders_out['金额'].sum():,.0f} | 利润合计 {orders_out['利润'].sum():,.0f}")


if __name__ == "__main__":
    main()
