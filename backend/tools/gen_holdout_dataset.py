"""生成留出集数据：门店客流（与销售数据不同域、不同列名）。

用途：在未参与任何提示词调整的新表上做一次性验证。
用法：python tools/gen_holdout_dataset.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "holdout_visits.db"
ROWS = 8_000
SEED = 777001

STORES = [
    ("S01", "徐汇店", "上海", "华东"),
    ("S02", "静安店", "上海", "华东"),
    ("S03", "滨江店", "杭州", "华东"),
    ("S04", "天河店", "广州", "华南"),
    ("S05", "南山店", "深圳", "华南"),
    ("S06", "国贸店", "北京", "华北"),
    ("S07", "南开店", "天津", "华北"),
    ("S08", "锦江店", "成都", "西南"),
]
LEVELS = ["普通", "白银", "黄金", "钻石"]


def main() -> None:
    rng = np.random.default_rng(SEED)
    stores = pd.DataFrame(STORES, columns=["门店编码", "门店名称", "城市", "区域"])

    days = pd.date_range("2026-03-01", "2026-08-31", freq="D")
    visits = pd.DataFrame({
        "编号": np.arange(1, ROWS + 1),
        "到店时间": pd.to_datetime(rng.choice(days, size=ROWS)).strftime("%Y-%m-%d"),
        "门店编码": rng.choice(stores["门店编码"].to_numpy(), size=ROWS),
        "会员等级": rng.choice(LEVELS, size=ROWS, p=[0.5, 0.28, 0.16, 0.06]),
        "消费金额": np.round(rng.gamma(2.0, 120.0, size=ROWS) + 20, 1),
    })
    visits["折扣金额"] = np.round(visits["消费金额"] * rng.uniform(0, 0.25, size=ROWS), 1)
    visits["实付金额"] = np.round(visits["消费金额"] - visits["折扣金额"], 1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    with sqlite3.connect(OUT) as conn:
        visits.to_sql("visits", conn, index=False)
        stores.to_sql("stores", conn, index=False)
        conn.execute("CREATE INDEX idx_visits_store ON visits(门店编码)")

    print(f"写入 {OUT}")
    print(f"visits: {len(visits)} 行 | stores: {len(stores)} 行")
    print(f"消费合计: {visits['消费金额'].sum():,.0f} | 实付合计: {visits['实付金额'].sum():,.0f}")


if __name__ == "__main__":
    main()
