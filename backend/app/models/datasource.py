"""数据源配置模型"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.time import utc_now_naive
from app.database import Base


class DataSource(Base):
    __tablename__ = "datasources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # excel | csv | mysql | postgres | sqlite
    config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON 连接配置
    table_schema: Mapped[str] = mapped_column(Text, nullable=True)  # JSON 表结构缓存
    # JSON：数据质量画像（列缺失率 / 唯一性 / 疑似敏感字段 / 风险提示）
    profile_json: Mapped[str] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    # 同时给 Python 端默认值：新建对象在 commit 后马上序列化也不会拿到未加载属性
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, server_default=func.now(), onupdate=func.now()
    )

