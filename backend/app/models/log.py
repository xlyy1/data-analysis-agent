"""操作日志模型"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # query | upload | report
    detail: Mapped[str] = mapped_column(Text, nullable=True)  # JSON 详情 (含 SQL、耗时等)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
