"""对话服务

管理会话生命周期、调用 LangGraph Agent、流式输出。
"""

import json
import uuid
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.agent.graph import agent_app
from app.agent.state import AgentState
from app.models.conversation import Conversation, Message
from app.datasource.factory import create_datasource
from app.config import get_settings


class ConversationService:
    """对话管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_conversation(self, user_id: str, title: str = "新对话") -> Conversation:
        conv = Conversation(
            id=str(uuid.uuid4()),
            title=title,
            user_id=user_id,
            datasource_ids="[]",
        )
        self.db.add(conv)
        await self.db.commit()
        return conv

    async def get_conversation(self, conv_id: str) -> Conversation | None:
        result = await self.db.execute(select(Conversation).where(Conversation.id == conv_id))
        return result.scalar_one_or_none()

    async def list_conversations(self, user_id: str) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_messages(self, conv_id: str) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_message(self, conv_id: str, role: str, content: str, metadata: dict | None = None) -> Message:
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role=role,
            content=content,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        self.db.add(msg)
        # 更新对话时间
        await self.db.execute(
            update(Conversation).where(Conversation.id == conv_id).values(updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return msg

    async def run_agent(
        self,
        conv_id: str,
        user_input: str,
        datasource_ids: list[str],
        datasource_schemas: list[str],
        datasource_configs: list[str],
    ) -> AgentState:
        """运行 Agent 并返回最终状态"""
        # 获取历史消息
        history = await self.get_messages(conv_id)
        history_messages = []
        for h in history[-20:]:
            history_messages.append({"role": h.role, "content": h.content})

        # 构建初始状态
        initial_state: AgentState = {
            "messages": [],
            "user_input": user_input,
            "datasource_ids": datasource_ids,
            "datasource_schemas": datasource_schemas,
            "datasource_configs": datasource_configs,
            "intent": "",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "generated_sql": "",
            "sql_explanation": "",
            "sql_needs_confirmation": False,
            "query_result_json": "{}",
            "analysis_type": "summary",
            "analysis_summary": "",
            "diagnosis_causes": [],
            "diagnosis_evidence": [],
            "diagnosis_suggestions": [],
            "chart_config_json": "{}",
            "final_response": "",
            "error": "",
        }

        # 运行 Graph
        result = await agent_app.ainvoke(initial_state)
        return result

    async def execute_sql_on_datasource(self, sql: str, datasource_id: str, datasource_config: dict) -> dict:
        """在指定数据源上执行 SQL"""
        ds = create_datasource(datasource_config["type"], datasource_config["config"])
        try:
            await ds.connect()
            result = await ds.execute_query(sql)
            await ds.disconnect()
            return {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "elapsed_ms": result.elapsed_ms,
            }
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": [], "row_count": 0, "elapsed_ms": 0}
