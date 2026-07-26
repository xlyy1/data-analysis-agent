"""数据源连接器测试"""

import pytest
import tempfile
import os


class TestExcelDataSource:
    """Excel 数据源测试"""

    @pytest.mark.asyncio
    async def test_parse_csv(self):
        from app.datasource.excel import ExcelDataSource

        csv_content = b"name,sales,cost\nA,100,60\nB,200,120\nC,150,90"
        ds = ExcelDataSource(file_content=csv_content, file_name="test.csv")

        await ds.connect()
        tables = await ds.get_tables()
        await ds.disconnect()

        assert len(tables) == 1
        assert tables[0].name == "test.csv"
        assert tables[0].row_count == 3
        assert len(tables[0].columns) == 3

    @pytest.mark.asyncio
    async def test_query_csv(self):
        from app.datasource.excel import ExcelDataSource

        csv_content = b"name,sales,cost\nA,100,60\nB,200,120\nC,150,90"
        ds = ExcelDataSource(file_content=csv_content, file_name="test.csv")

        await ds.connect()
        result = await ds.execute_query("SELECT name, SUM(sales) as total FROM 'test.csv' GROUP BY name")
        await ds.disconnect()

        assert result.row_count == 3
        assert "name" in result.columns

    @pytest.mark.asyncio
    async def test_query_aggregation(self):
        from app.datasource.excel import ExcelDataSource

        csv_content = b"product,category,revenue\nX,A,100\nY,A,200\nZ,B,150"
        ds = ExcelDataSource(file_content=csv_content, file_name="data.csv")

        await ds.connect()
        result = await ds.execute_query("SELECT category, SUM(revenue) as total_revenue FROM 'data.csv' GROUP BY category")
        await ds.disconnect()

        assert result.row_count == 2


class TestSQLiteDataSource:
    """外部 SQLite 数据源测试"""

    @pytest.mark.asyncio
    async def test_connect_and_query(self):
        import sqlite3

        # 创建测试数据库
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE test (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello'), (2, 'world')")
        conn.commit()
        conn.close()

        try:
            from app.datasource.sqlite import SQLiteDataSource

            ds = SQLiteDataSource(db_path=path)
            await ds.connect()
            tables = await ds.get_tables()
            result = await ds.execute_query("SELECT * FROM test ORDER BY id")
            await ds.disconnect()

            assert len(tables) == 1
            assert tables[0].name == "test"
            assert result.row_count == 2
        finally:
            os.unlink(path)


class TestDataSourceFactory:
    """数据源工厂测试"""

    def test_create_excel(self):
        from app.datasource.factory import create_datasource
        ds = create_datasource("excel", {"file_name": "test.xlsx"})
        assert ds.source_type == "excel"

    def test_create_mysql(self):
        from app.datasource.factory import create_datasource
        ds = create_datasource("mysql", {"host": "localhost", "port": 3306, "user": "root", "password": "", "database": "test"})
        assert ds.source_type == "mysql"

    def test_unknown_type_raises(self):
        from app.datasource.factory import create_datasource
        with pytest.raises(ValueError):
            create_datasource("unknown", {})
