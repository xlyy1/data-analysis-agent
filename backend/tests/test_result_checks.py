"""结果校验测试：数值域、分组对账、总计 SQL 推导。"""
from app.agent.validators import (
    build_total_sql,
    check_group_nulls,
    check_numeric_domains,
    numeric_columns,
    reconcile,
)


class TestNumericDomains:
    def test_rate_over_one_is_flagged(self):
        warnings = check_numeric_domains(["profit_rate"], [[3.0]])
        assert warnings and "除以基数" in warnings[0]["message"]

    def test_normal_rate_passes(self):
        assert check_numeric_domains(["profit_rate"], [[0.03], [0.05]]) == []

    def test_negative_count_is_flagged(self):
        warnings = check_numeric_domains(["销量"], [[-5]])
        assert warnings and "不应为负" in warnings[0]["message"]

    def test_negative_profit_is_allowed(self):
        assert check_numeric_domains(["利润"], [[-500]]) == [], "亏损是正常业务结果，不该告警"

    def test_extreme_growth_is_flagged(self):
        warnings = check_numeric_domains(["增长率"], [[50.0]])
        assert warnings and "极端值" in warnings[0]["message"]

    def test_non_numeric_column_is_ignored(self):
        assert check_numeric_domains(["region"], [["华东"]]) == []


class TestGroupNulls:
    def test_null_group_is_reported(self):
        warnings = check_group_nulls(["region", "amount"], [[None, 10]])
        assert warnings and "未归入任何分组" in warnings[0]["message"]

    def test_no_null_passes(self):
        assert check_group_nulls(["region"], [["华东"]]) == []


class TestTotalSql:
    def test_simple_group_by(self):
        sql = "SELECT region, SUM(amount) FROM orders WHERE dt >= '2026-01-01' GROUP BY region"
        assert build_total_sql(sql) == (
            "SELECT SUM(amount) AS __total FROM orders WHERE dt >= '2026-01-01'"
        )

    def test_without_group_by_returns_none(self):
        assert build_total_sql("SELECT SUM(amount) FROM orders") is None

    def test_multiple_sums_returns_none(self):
        sql = "SELECT a, SUM(x), SUM(y) FROM t GROUP BY a"
        assert build_total_sql(sql) is None

    def test_subquery_returns_none(self):
        sql = "SELECT a, SUM(x) FROM (SELECT * FROM t) s GROUP BY a"
        assert build_total_sql(sql) is None


class TestReconcile:
    def test_matching_totals_pass(self):
        assert reconcile(100.0, 100.0) == []

    def test_small_diff_within_tolerance(self):
        assert reconcile(100.0, 100.5) == []

    def test_large_diff_is_flagged(self):
        warnings = reconcile(100.0, 130.0)
        assert warnings and "对账不一致" in warnings[0]["message"]

    def test_missing_side_skips(self):
        assert reconcile(None, 100.0) == []
        assert reconcile(100.0, None) == []


class TestNumericColumns:
    def test_detects_numeric_indexes(self):
        columns = ["region", "amount"]
        rows = [["华东", 10], ["华南", 20]]
        assert numeric_columns(columns, rows) == [1]

    def test_all_text_returns_empty(self):
        assert numeric_columns(["region"], [["华东"]]) == []
