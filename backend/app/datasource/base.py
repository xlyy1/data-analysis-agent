"""数据源抽象基类

每种数据源实现统一的接口：connect → get_schema → execute_query
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ColumnInfo:
    name: str
    dtype: str
    nullable: bool = True


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    row_count: int = 0


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    elapsed_ms: float
    query: str


class BaseDataSource(ABC):
    """数据源统一接口"""

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """关闭连接"""
        ...

    @abstractmethod
    async def get_tables(self) -> list[TableInfo]:
        """获取所有表的 schema 信息"""
        ...

    @abstractmethod
    async def execute_query(self, sql: str, params: dict | None = None) -> QueryResult:
        """执行 SELECT 查询，返回结构化结果"""
        ...

    @property
    @abstractmethod
    def source_type(self) -> str:
        ...
