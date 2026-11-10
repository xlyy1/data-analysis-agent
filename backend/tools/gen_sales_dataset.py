"""生成规模化测试数据：3 万行订单 + 产品维表，写入 SQLite。

用于验证 Text-to-SQL 在真实数据量、多表 JOIN 下的表现。
用法：python tools/gen_sales_dataset.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "sales_large.db"
ROWS = 30_000
SEED = 20261110

PRODUCTS = [
    ("P01", "充电宝", "手机配件", 79, 45),
    ("P02", "数据线", "手机配件", 29, 12),
    ("P03", "手机壳", "手机配件", 39, 15),
    ("P04", "无线鼠标", "电脑外设", 129, 78),
    ("P05", "机械键盘", "电脑外设", 399, 240),
    ("P06", "显示器支架", "电脑外设", 259, 150),
    ("P07", "智能手环", "穿戴设备", 199, 110),
    ("P08", "智能手表", "穿戴设备", 599, 380),
    ("P09", "运动耳机", "音频设备", 299, 170),
    ("P10", "蓝牙音箱", "音频设备", 249, 140),
    ("P11", "降噪耳机", "音频设备", 899, 560),
    ("P12", "扩展坞", "电脑外设", 189, 105),
]
CHANNELS = ["京东", "淘宝", "拼多多", "抖音", "苏宁"]
CITIES = ["上海", "北京", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "苏州", "重庆", "天津"]


def main() -> None:
    rng = np.random.default_rng(SEED)

    products = pd.DataFrame(PRODUCTS, columns=["产品ID", "产品名称", "产品类别", "售价", "成本价"])

    n = ROWS
    product_ids = products["产品ID"].to_numpy()
    # 日期：2026-01-01 至 2026-12-31，按真实分布起伏
    days = pd.date_range("2026-01-01", "2026-12-31", freq="D")
    weights = np.linspace(1.0, 1.6, len(days))
    weights[days.month.isin([6, 11, 12])] *= 1.5
    weights = weights / weights.sum()
    order_dates = rng.choice(days, size=n, p=weights)

    orders = pd.DataFrame({
        "订单ID": np.arange(1, n + 1),
        "订单日期": pd.to_datetime(order_dates).strftime("%Y-%m-%d"),
        "产品ID": rng.choice(product_ids, size=n),
        "销售渠道": rng.choice(CHANNELS, size=n, p=[0.32, 0.30, 0.18, 0.12, 0.08]),
        "客户城市": rng.choice(CITIES, size=n),
        "销量": rng.integers(1, 21, size=n),
    })

    merged = orders.merge(products, on="产品ID", how="left")
    merged["销售额"] = merged["销量"] * merged["售价"]
    merged["成本"] = merged["销量"] * merged["成本价"]
    merged["利润"] = merged["销售额"] - merged["成本"]

    orders_out = merged[["订单ID", "订单日期", "产品ID", "销售渠道", "客户城市", "销量", "销售额", "成本", "利润"]]
    products_out = products[["产品ID", "产品名称", "产品类别", "售价", "成本价"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    with sqlite3.connect(OUT) as conn:
        orders_out.to_sql("orders", conn, index=False)
        products_out.to_sql("products", conn, index=False)
        conn.execute("CREATE INDEX idx_orders_date ON orders(订单日期)")
        conn.execute("CREATE INDEX idx_orders_product ON orders(产品ID)")

    print(f"写入 {OUT}")
    print(f"orders: {len(orders_out)} 行 | products: {len(products_out)} 行")
    print(f"时间范围: {orders_out['订单日期'].min()} ~ {orders_out['订单日期'].max()}")
    print(f"销售额合计: {orders_out['销售额'].sum():,.0f} | 利润合计: {orders_out['利润'].sum():,.0f}")


if __name__ == "__main__":
    main()
