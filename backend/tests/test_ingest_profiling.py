"""数据管道测试：清洗规则、增量幂等、schema profiling、敏感字段识别。"""

from __future__ import annotations


import pandas as pd
import pytest

from app.datasource.sqlite import SQLiteDataSource
from app.services.ingest import (
    HASH_COLUMN,
    clean_frame,
    ingest_bytes,
    ingest_frame,
    read_table,
    safe_table_name,
)
from app.services.profiling import profile_datasource
from app.core.sqlite import sqlite_connection


class TestCleaning:
    def test_column_names_normalized(self):
        df = pd.DataFrame({" 门店编号 ": [1], "": [2], "城市": [3], "城市_": [4]})
        cleaned, notes, _, _ = clean_frame(df)
        assert list(cleaned.columns) == ["门店编号", "col_2", "城市", "城市_"]
        assert any("没有列名" in note for note in notes)

    def test_duplicate_column_names_suffixed(self):
        df = pd.DataFrame([[1, 2]], columns=["a", "a"])
        cleaned, notes, _, _ = clean_frame(df)
        assert len(set(cleaned.columns)) == 2
        assert any("列名重复" in note for note in notes)

    def test_blank_rows_dropped(self):
        df = pd.DataFrame({"a": [1, None, 3], "b": ["x", None, "z"]})
        cleaned, _, blank, _ = clean_frame(df)
        assert blank == 1
        assert len(cleaned) == 2

    def test_exact_duplicates_dropped(self):
        df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
        cleaned, _, _, duplicates = clean_frame(df)
        assert duplicates == 1
        assert len(cleaned) == 2

    def test_strings_stripped_and_empty_to_null(self):
        df = pd.DataFrame({"name": ["  A店 ", "", "B店"], "city": ["杭州", "苏州", "宁波"]})
        cleaned, _, blank, _ = clean_frame(df)
        assert blank == 0, "只有一个单元格为空的行不应被当成空行丢弃"
        assert cleaned["name"].tolist()[0] == "A店"
        assert pd.isna(cleaned["name"].tolist()[1])
        assert cleaned["name"].tolist()[2] == "B店"

    def test_all_empty_row_dropped_after_blank_normalization(self):
        df = pd.DataFrame({"a": ["1", "", "3"], "b": ["x", "", "z"]})
        cleaned, _, blank, _ = clean_frame(df)
        assert blank == 1
        assert len(cleaned) == 2

    def test_leading_zero_codes_stay_text(self):
        df = pd.DataFrame({"门店编号": ["0012", "0301", "0007"]})
        cleaned, notes, _, _ = clean_frame(df)
        assert not pd.api.types.is_numeric_dtype(cleaned["门店编号"])
        assert cleaned["门店编号"].tolist() == ["0012", "0301", "0007"]
        assert any("前导零" in note for note in notes)

    def test_numeric_strings_coerced(self):
        df = pd.DataFrame({"销售额": ["100", "200", "300"]})
        cleaned, _, _, _ = clean_frame(df)
        assert pd.api.types.is_numeric_dtype(cleaned["销售额"])

    def test_mixed_text_not_coerced(self):
        df = pd.DataFrame({"备注": ["100", "未知", "不适用"]})
        cleaned, _, _, _ = clean_frame(df)
        assert not pd.api.types.is_numeric_dtype(cleaned["备注"])


class TestTableName:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("门店经营明细.csv", "门店经营明细"),
            ("sales 2026-01.xlsx", "sales_2026_01"),
            ("../../etc/passwd.csv", "passwd"),
            ("", "data"),
        ],
    )
    def test_safe_table_name(self, filename: str, expected: str):
        assert safe_table_name(filename) == expected


class TestIngestFrame:
    def test_writes_rows_and_hash_column(self, tmp_path):
        df = pd.DataFrame({"city": ["A", "B"], "amount": [1.0, 2.0]})
        result = ingest_frame(df, db_path=tmp_path / "x.db", table="t")
        assert result.rows_written == 2
        assert result.columns == ["city", "amount"]
        with sqlite_connection(tmp_path / "x.db") as conn:
            columns = [row[1] for row in conn.execute('PRAGMA table_info("t")')]
            assert HASH_COLUMN in columns

    def test_append_is_idempotent(self, tmp_path):
        df = pd.DataFrame({"city": ["A", "B"], "amount": [1.0, 2.0]})
        db = tmp_path / "x.db"
        first = ingest_frame(df, db_path=db, table="t")
        assert first.rows_written == 2

        second = ingest_frame(df, db_path=db, table="t", append=True)
        assert second.rows_written == 0, "重复上传同一份数据不应新增行"
        with sqlite_connection(db) as conn:
            assert conn.execute('SELECT COUNT(*) FROM "t"').fetchone()[0] == 2

    def test_append_only_adds_new_rows(self, tmp_path):
        db = tmp_path / "x.db"
        ingest_frame(pd.DataFrame({"city": ["A"], "amount": [1.0]}), db_path=db, table="t")
        result = ingest_frame(
            pd.DataFrame({"city": ["A", "B"], "amount": [1.0, 9.0]}),
            db_path=db,
            table="t",
            append=True,
        )
        assert result.rows_written == 1
        with sqlite_connection(db) as conn:
            assert conn.execute('SELECT COUNT(*) FROM "t"').fetchone()[0] == 2

    def test_replace_mode_drops_previous_table(self, tmp_path):
        db = tmp_path / "x.db"
        ingest_frame(pd.DataFrame({"city": ["A", "B"]}), db_path=db, table="t")
        result = ingest_frame(pd.DataFrame({"city": ["C"]}), db_path=db, table="t")
        assert result.rows_written == 1
        with sqlite_connection(db) as conn:
            assert conn.execute('SELECT COUNT(*) FROM "t"').fetchone()[0] == 1


class TestIngestBytes:
    def test_csv_utf8_bom(self, tmp_path):
        content = "城市,销售额\n杭州,100\n苏州,200\n".encode("utf-8-sig")
        result = ingest_bytes(content, "sales.csv", db_path=tmp_path / "x.db")
        assert result.encoding == "utf-8-sig"
        assert result.rows_written == 2

    def test_csv_gbk_fallback(self, tmp_path):
        content = "城市,销售额\n杭州,100\n".encode("gbk")
        result = ingest_bytes(content, "sales.csv", db_path=tmp_path / "x.db")
        assert result.encoding == "gbk"

    def test_unsupported_suffix_raises(self, tmp_path):
        with pytest.raises(ValueError):
            read_table(b"abc", "data.txt")

    def test_messy_csv_reports_cleaning(self, tmp_path):
        content = (
            " 门店编号 ,城市,销售额\n"
            "0012, 杭州 ,100\n"
            "0012, 杭州 ,100\n"
            ",,\n"
        ).encode("utf-8")
        result = ingest_bytes(content, "门店.csv", db_path=tmp_path / "x.db")
        assert result.dropped_blank == 1
        assert result.dropped_duplicate == 1
        assert result.rows_written == 1
        assert any("前导零" in note for note in result.notes)


@pytest.fixture()
def profile_db(tmp_path):
    path = tmp_path / "sales.db"
    with sqlite_connection(path) as conn:
        conn.execute(
            'CREATE TABLE orders (id INTEGER PRIMARY KEY, city TEXT, phone TEXT, amount REAL, note TEXT)'
        )
        conn.executemany(
            'INSERT INTO orders (id, city, phone, amount, note) VALUES (?,?,?,?,?)',
            [
                (1, "杭州", "13800000001", 100.0, None),
                (2, "杭州", "13800000002", 200.0, None),
                (3, "苏州", "13800000003", 300.0, None),
                (4, "苏州", "13800000003", 300.0, None),
            ],
        )
        conn.commit()
    return path


class TestProfiling:
    async def test_profile_columns(self, profile_db):
        connector = SQLiteDataSource(str(profile_db))
        await connector.connect()
        try:
            result = await profile_datasource(connector)
        finally:
            await connector.disconnect()

        assert result["table_count"] == 1
        table = result["tables"][0]
        assert table["row_count"] == 4
        by_name = {column["name"]: column for column in table["columns"]}

        assert by_name["id"]["is_unique"] is True
        assert by_name["city"]["distinct_count"] == 2
        assert {item["value"] for item in by_name["city"]["top_values"]} == {"杭州", "苏州"}
        assert by_name["note"]["null_rate"] == 1.0
        assert by_name["phone"]["is_pii"] is True
        assert by_name["phone"]["pii_kind"] == "phone"
        assert any("缺失率" in risk for risk in table["risks"])

    async def test_duplicate_detection_without_primary_key(self, tmp_path):
        path = tmp_path / "dupes.db"
        with sqlite_connection(path) as conn:
            conn.execute("CREATE TABLE sales (city TEXT, amount REAL)")
            conn.executemany(
                "INSERT INTO sales VALUES (?,?)",
                [("杭州", 100.0), ("杭州", 100.0), ("苏州", 200.0)],
            )
            conn.commit()

        connector = SQLiteDataSource(str(path))
        await connector.connect()
        try:
            result = await profile_datasource(connector)
        finally:
            await connector.disconnect()

        table = result["tables"][0]
        assert table["duplicate_groups"] == 1
        assert any("重复" in risk for risk in table["risks"])

    async def test_profile_missing_table(self, profile_db):
        connector = SQLiteDataSource(str(profile_db))
        await connector.connect()
        try:
            from app.services.profiling import profile_table

            result = await profile_table(connector, "nope")
        finally:
            await connector.disconnect()
        assert result["error"] == "表不存在"
