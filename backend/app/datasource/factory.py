"""数据源工厂 — 根据配置创建对应的数据源实例"""

import json

from app.datasource.base import BaseDataSource
from app.datasource.excel import ExcelDataSource
from app.datasource.mysql import MySQLDataSource
from app.datasource.postgres import PostgresDataSource
from app.datasource.sqlite import SQLiteDataSource


def create_datasource(ds_type: str, config: dict | str) -> BaseDataSource:
    """根据类型和配置创建数据源实例。

    excel / csv 上传后会落一份清洗过的 SQLite（config["ingested_db"]），
    有它就直接查库；没有（老数据源 / 未清洗）才退回内存 DataFrame 模式。
    """
    if isinstance(config, str):
        config = json.loads(config)

    if ds_type in ("excel", "csv"):
        ingested = config.get("ingested_db")
        if ingested:
            return SQLiteDataSource(db_path=ingested)
        return ExcelDataSource(
            file_path=config.get("file_path"),
            file_content=None,
            file_name=config.get("file_name", "data.xlsx"),
        )
    if ds_type == "mysql":
        return MySQLDataSource(
            host=config["host"],
            port=config.get("port", 3306),
            user=config["user"],
            password=config["password"],
            database=config["database"],
        )
    if ds_type == "postgres":
        return PostgresDataSource(
            host=config["host"],
            port=config.get("port", 5432),
            user=config["user"],
            password=config["password"],
            database=config["database"],
        )
    if ds_type == "sqlite":
        return SQLiteDataSource(db_path=config["db_path"])
    raise ValueError(f"Unknown datasource type: {ds_type}")


SUPPORTED_TYPES = ("sqlite", "mysql", "postgres", "excel", "csv")

# 每种类型必填的配置键，用于创建数据源前的前置校验（避免"存进去了但永远连不上"）
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "sqlite": ("db_path",),
    "mysql": ("host", "user", "password", "database"),
    "postgres": ("host", "user", "password", "database"),
    "excel": ("file_path",),
    "csv": ("file_path",),
}
