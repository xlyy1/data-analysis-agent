"""对话服务

管理会话生命周期、调用 LangGraph Agent、流式输出。
"""

import json
import time
import uuid
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.agent.context import compact_history, make_llm_summarizer
from app.agent.graph import agent_app
from app.agent.orchestrator import SubTask, dispatch
from app.agent.state import AgentState
from app.llm.factory import get_llm
from app.models.conversation import Conversation, Message
from app.datasource.factory import create_datasource
from app.config import get_settings
from app.observability.trace import new_trace_id, record as record_trace


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
        settings = get_settings()
        task_id = new_trace_id()

        # 历史消息：超过预算时压缩成「摘要 + 近窗」，避免长会话线性膨胀
        history = await self.get_messages(conv_id)
        history_messages = [{"role": h.role, "content": h.content} for h in history]
        compacted = await compact_history(
            history_messages,
            max_tokens=settings.context_max_tokens,
            keep_recent=settings.context_keep_recent,
            summarize=make_llm_summarizer(get_llm()),
        )
        if compacted.compacted:
            record_trace(task_id, "context_compact", "ok", time.time(), 0.0, fields=compacted.stats())

        # 构建初始状态
        initial_state: AgentState = {
            "messages": compacted.messages,
            "trace_id": task_id,
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
            "sql_retry_count": 0,
            "sql_error": "",
            "empty_result": False,
            "result_warnings": [],
            "datasource_status": [],
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

        # 运行 Graph：主路径失败时，把失败原因回灌给模型重试一次（supervisor 调度）
        async def run_pipeline(state: dict) -> dict:
            return await agent_app.ainvoke(state)

        async def run_pipeline_with_feedback(state: dict) -> dict:
            retry_state = dict(state)
            retry_state["user_input"] = (
                f"{state['user_input']}\n\n（上一次执行失败：{state.get('error') or '未产出结果'}。"
                "请修正后重新生成，只返回最终结果。）"
            )
            retry_state["sql_retry_count"] = 0
            return await agent_app.ainvoke(retry_state)

        dispatch_result = await dispatch(
            [
                SubTask("pipeline", run_pipeline, description="主分析链路", max_attempts=1, timeout_s=180.0),
                SubTask(
                    "pipeline_repair",
                    run_pipeline_with_feedback,
                    description="带失败回灌的重试链路",
                    max_attempts=1,
                    timeout_s=180.0,
                ),
            ],
            initial_state,
            task_id=task_id,
        )
        result = dispatch_result.state
        if dispatch_result.failed:
            result = {
                **result,
                "final_response": result.get("final_response") or "分析链路执行失败，请稍后重试或换个问法。",
                "error": "; ".join(dispatch_result.notes) or result.get("error", ""),
            }
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
