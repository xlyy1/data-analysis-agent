"""缓存评测结果的回归门（不需要 API Key）。

`backend/tests/data/*.result.json` 是 DeepSeek 历史上跑出来的**真实**评测结果
（309 条 NL2SQL 用例，含两套未参与调参的留出集）。CI 里不去重跑（要花钱、有随机性），
而是校验这些已归档的结果本身仍然达标；将来谁重跑并把结果覆盖成更差的数字，
这里会直接失败。

用法：python bench/quality_gate.py [--strict]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"

# 每套评测的最低要求：正确率、可执行率、最小用例数（防止被"缩表"糊弄过去）
THRESHOLDS: dict[str, dict] = {
    "text2sql.result.json": {"correct_rate": 1.0, "exec_rate": 1.0, "cases": 191},
    "text2sql_holdout.result.json": {"correct_rate": 1.0, "exec_rate": 1.0, "cases": 25},
    "text2sql_holdout2.result.json": {"correct_rate": 1.0, "exec_rate": 1.0, "cases": 22},
    "text2sql_join.result.json": {"correct_rate": 1.0, "exec_rate": 1.0, "cases": 41},
    "text2sql_scale.result.json": {"correct_rate": 1.0, "exec_rate": 1.0, "cases": 30},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="缺文件也算失败")
    args = parser.parse_args()

    failures: list[str] = []
    total_cases = 0
    for filename, limits in THRESHOLDS.items():
        path = DATA / filename
        if not path.exists():
            message = f"{filename}: 缺少评测结果文件"
            (failures if args.strict else []).append(message)
            print(f"[SKIP] {message}")
            continue

        summary = json.loads(path.read_text(encoding="utf-8"))["summary"]
        cases = int(summary.get("cases", 0))
        total_cases += cases
        for key in ("correct_rate", "exec_rate", "cases"):
            actual = float(summary.get(key, 0.0))
            expected = float(limits[key])
            ok = actual >= expected
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {filename}: {key}={actual:g} (要求 >= {expected:g}, cases={cases})")
            if not ok:
                failures.append(f"{filename}: {key} {actual:g} < {expected:g}")

    print(f"\n归档用例总数：{total_cases}")
    if failures:
        print("未达标：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("QUALITY GATE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
