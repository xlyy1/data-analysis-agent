"""对话与消息模型"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(256), default="新对话")
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    datasource_ids: Mapped[str] = mapped_column(Text, nullable=True)  # JSON 数组
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 额外元数据 (SQL、图表配置等)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True, name="metadata")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
