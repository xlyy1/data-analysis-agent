"""数据源工厂 — 根据配置创建对应的数据源实例"""

import json
from app.datasource.base import BaseDataSource
from app.datasource.excel import ExcelDataSource
from app.datasource.mysql import MySQLDataSource
from app.datasource.postgres import PostgresDataSource
from app.datasource.sqlite import SQLiteDataSource


def create_datasource(ds_type: str, config: dict | str) -> BaseDataSource:
    """根据类型和配置创建数据源实例"""
    if isinstance(config, str):
        config = json.loads(config)

    if ds_type == "excel":
        return ExcelDataSource(
            file_path=config.get("file_path"),
            file_content=None,
            file_name=config.get("file_name", "data.xlsx"),
        )
    elif ds_type == "csv":
        return ExcelDataSource(
            file_path=config.get("file_path"),
            file_content=None,
            file_name=config.get("file_name", "data.csv"),
        )
    elif ds_type == "mysql":
        return MySQLDataSource(
            host=config["host"],
            port=config.get("port", 3306),
            user=config["user"],
            password=config["password"],
            database=config["database"],
        )
    elif ds_type == "postgres":
        return PostgresDataSource(
            host=config["host"],
            port=config.get("port", 5432),
            user=config["user"],
            password=config["password"],
            database=config["database"],
        )
    elif ds_type == "sqlite":
        return SQLiteDataSource(db_path=config["db_path"])
    else:
        raise ValueError(f"Unknown datasource type: {ds_type}")
