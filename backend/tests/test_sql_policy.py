"""SQL 安全策略测试：只读 / 单语句 / 长度 / 自动 LIMIT / 注释与字面量干扰。"""

from __future__ import annotations

import pytest

from app.services.sql_policy import cap_cells, guard_sql


def g(sql: str, **kwargs):
    return guard_sql(sql, max_chars=kwargs.pop("max_chars", 8000), default_limit=kwargs.pop("default_limit", 100), **kwargs)


class TestRejectsWrites:
    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE orders",
            "DELETE FROM orders",
            "UPDATE orders SET amount = 0",
            "INSERT INTO orders VALUES (1)",
            "ALTER TABLE orders ADD COLUMN x INT",
            "CREATE TABLE t (a INT)",
            "TRUNCATE TABLE orders",
            "GRANT ALL ON orders TO public",
            "ATTACH DATABASE '/tmp/x.db' AS x",
            "PRAGMA table_info('orders')",
            "VACUUM",
            "REINDEX",
        ],
    )
    def test_write_statements_blocked(self, sql: str):
        decision = g(sql)
        assert decision.ok is False
        assert decision.code in {"sql_write_forbidden", "sql_not_readonly"}
        assert "只允许只读查询" in decision.reason or "暂不支持" in decision.reason

    def test_cte_with_delete_blocked(self):
        decision = g('WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x')
        assert decision.ok is False

    def test_cte_without_select_blocked(self):
        decision = g("WITH x AS (VALUES (1))")
        assert decision.ok is False

    def test_multi_statement_blocked(self):
        decision = g('SELECT 1; DROP TABLE "订单明细"')
        assert decision.ok is False
        assert decision.code == "sql_multi_statement"

    def test_trailing_semicolon_is_fine(self):
        decision = g("SELECT 1;")
        assert decision.ok is True
        assert decision.sql == "SELECT 1\nLIMIT 100"

    def test_allow_write_does_not_unlock_ddl(self):
        # 即便上层显式允许写，DDL/多语句仍然拒绝（纵深防御）
        decision = g("DROP TABLE orders", allow_write=True)
        assert decision.ok is False


class TestRejectsDangerousPatterns:
    @pytest.mark.parametrize(
        "sql,keyword",
        [
            ("SELECT load_file('/etc/passwd')", "服务器文件"),
            ("SELECT pg_read_file('/etc/passwd')", "服务器文件"),
            ("SELECT * INTO OUTFILE '/tmp/x' FROM orders", "导出到文件"),
            ("SELECT * INTO DUMPFILE '/tmp/x' FROM orders", "导出到文件"),
            ("SELECT xp_cmdshell('dir')", "系统命令"),
            ("SELECT SLEEP(10)", "延时注入"),
            ("SELECT BENCHMARK(1000000, MD5('a'))", "压力函数"),
        ],
    )
    def test_patterns_blocked(self, sql: str, keyword: str):
        decision = g(sql)
        assert decision.ok is False
        assert keyword in decision.reason


class TestAcceptsReadOnly:
    def test_plain_select_gets_limit(self):
        decision = g('SELECT "城市", SUM("销售额") FROM "订单明细" GROUP BY 1')
        assert decision.ok is True
        assert decision.applied_limit == 100
        assert decision.sql.endswith("LIMIT 100")

    def test_existing_limit_untouched(self):
        decision = g("SELECT a FROM t LIMIT 5")
        assert decision.ok is True
        assert decision.applied_limit is None
        assert decision.sql == "SELECT a FROM t LIMIT 5"

    def test_explain_allowed(self):
        assert g("EXPLAIN SELECT 1").ok is True

    def test_show_and_describe_allowed(self):
        assert g("SHOW TABLES").ok is True
        assert g("DESCRIBE orders").ok is True

    def test_string_literal_with_keyword_is_fine(self):
        decision = g("SELECT * FROM t WHERE comment = 'delete me; drop table x'")
        assert decision.ok is True

    def test_quoted_identifier_is_fine(self):
        decision = g('SELECT "update", "delete" FROM "订单明细"')
        assert decision.ok is True

    def test_replace_function_is_fine(self):
        decision = g("SELECT REPLACE(name, 'a', 'b') FROM t")
        assert decision.ok is True

    def test_comment_is_masked_not_rejected(self):
        decision = g("SELECT 1 -- drop table x\n")
        assert decision.ok is True

    def test_limit_is_outside_trailing_line_comment(self):
        decision = g("SELECT 1 -- note")
        assert decision.ok is True
        assert "\nLIMIT 100" in decision.sql


class TestLimits:
    def test_empty_rejected(self):
        assert g("   ").code == "sql_empty"

    def test_too_long_rejected(self):
        decision = g("SELECT 1" + " , 1" * 500, max_chars=100)
        assert decision.code == "sql_too_long"

    def test_cap_cells_shrinks_wide_tables(self):
        # 1000 列 × 10000 行会超 20 万个单元格，必须按列数折算
        assert cap_cells(1000, 10000, max_cells=200_000) == 200
        assert cap_cells(1, 10000, max_cells=200_000) == 10000
        assert cap_cells(0, 5, max_cells=200_000) == 5
