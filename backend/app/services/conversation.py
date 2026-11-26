"""对话服务

管理会话生命周期、调用 LangGraph Agent、流式输出。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import compact_history, make_llm_summarizer
from app.agent.graph import agent_app
from app.agent.orchestrator import SubTask, dispatch
from app.agent.state import AgentState
from app.config import get_settings
from app.datasource.factory import create_datasource
from app.llm.factory import get_llm
from app.models.conversation import Conversation, Message
from app.observability.metrics import agent_run_duration, agent_runs_total
from app.observability.trace import new_trace_id, record as record_trace


class ConversationService:
    """对话管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------ 会话 CRUD

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

    async def get_conversation(self, conv_id: str, owner_id: str | None = None) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == conv_id)
        if owner_id is not None:
            stmt = stmt.where(Conversation.user_id == owner_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

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

    async def add_message(
        self, conv_id: str, role: str, content: str, metadata: dict | None = None
    ) -> Message:
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role=role,
            content=content,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        self.db.add(msg)
        await self.db.execute(
            update(Conversation).where(Conversation.id == conv_id).values(updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return msg

    # ------------------------------------------------------------ Agent 执行

    async def _initial_state(
        self,
        conv_id: str,
        user_input: str,
        datasource_ids: list[str],
        datasource_schemas: list[str],
        datasource_configs: list[str],
        allow_write: bool,
        user_id: str = "",
    ) -> AgentState:
        settings = get_settings()
        task_id = new_trace_id()

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

        return {
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
            "allow_write": allow_write,
            "user_id": user_id,
            "error_non_retryable": False,
        }

    async def run_agent(
        self,
        conv_id: str,
        user_input: str,
        datasource_ids: list[str],
        datasource_schemas: list[str],
        datasource_configs: list[str],
        *,
        allow_write: bool = False,
        user_id: str = "",
        on_event: Callable[[dict], Awaitable[None]] | None = None,
    ) -> AgentState:
        """运行 Agent 并返回最终状态。

        on_event 非空时改走 astream，把每个节点的推进实时抛给调用方（SSE 用），
        仍然复用同一张图，非流式路径的行为完全不变。
        """
        initial_state = await self._initial_state(
            conv_id,
            user_input,
            datasource_ids,
            datasource_schemas,
            datasource_configs,
            allow_write,
            user_id,
        )
        started = time.perf_counter()
        try:
            if on_event is not None:
                result = await self._run_streaming(initial_state, on_event)
            else:
                result = await self._run_dispatched(initial_state)
        except Exception:  # noqa: BLE001 - 指标要记录失败，异常继续抛
            agent_runs_total.inc(outcome="error")
            raise
        agent_run_duration.observe(time.perf_counter() - started)
        agent_runs_total.inc(outcome="error" if result.get("error") else "ok")
        return result

    async def _run_dispatched(self, state: AgentState) -> AgentState:
        async def run_pipeline(payload: dict) -> dict:
            return await agent_app.ainvoke(payload)

        async def run_pipeline_with_feedback(payload: dict) -> dict:
            retry_state = dict(payload)
            retry_state["user_input"] = (
                f"{payload['user_input']}\n\n（上一次执行失败：{payload.get('error') or '未产出结果'}。"
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
            state,
            task_id=state["trace_id"],
        )
        result = dispatch_result.state
        if dispatch_result.failed:
            result = {
                **result,
                "final_response": result.get("final_response")
                or "分析链路执行失败，请稍后重试或换个问法。",
                "error": "; ".join(dispatch_result.notes) or result.get("error", ""),
            }
        return result

    async def _run_streaming(
        self, state: AgentState, on_event: Callable[[dict], Awaitable[None]]
    ) -> AgentState:
        merged: dict = dict(state)
        try:
            async for chunk in agent_app.astream(state, stream_mode="updates"):
                for node_name, partial in chunk.items():
                    await on_event({"type": "node", "node": node_name})
                    if isinstance(partial, dict):
                        merged.update(partial)
            merged.setdefault("trace_id", state["trace_id"])
            return merged  # type: ignore[return-value]
        except Exception as error:  # noqa: BLE001 - 流式中断后退化为一次性重试
            await on_event({"type": "node", "node": "retry", "error": str(error)[:200]})
            retry_state = dict(state)
            retry_state["user_input"] = (
                f"{state['user_input']}\n\n（上一次执行失败：{error}。请修正后重新生成，只返回最终结果。）"
            )
            return await agent_app.ainvoke(retry_state)  # type: ignore[return-value]

    # ------------------------------------------------------------ 直连执行

    async def execute_sql_on_datasource(
        self, sql: str, datasource_id: str, datasource_config: dict
    ) -> dict:
        """在指定数据源上执行 SQL（报告 / 定时任务复用）。"""
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
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "columns": [], "rows": [], "row_count": 0, "elapsed_ms": 0}


def build_assistant_metadata(state: dict) -> dict:
    """把 Agent 终态压成随消息落库的元数据（对话接口与定时任务共用）。"""
    query_result = json.loads(state.get("query_result_json") or "{}")
    return {
        "sql": state.get("generated_sql", ""),
        "executed_sql": query_result.get("executed_sql", ""),
        "sql_explanation": state.get("sql_explanation", ""),
        "analysis_type": state.get("analysis_type", ""),
        "chart_config": json.loads(state.get("chart_config_json") or "{}"),
        "diagnosis_causes": state.get("diagnosis_causes", []),
        "diagnosis_suggestions": state.get("diagnosis_suggestions", []),
        "result_warnings": state.get("result_warnings", []),
        "datasource_status": state.get("datasource_status", []),
        "trace_id": state.get("trace_id", ""),
        "data_columns": query_result.get("columns", []),
        "data_rows": (query_result.get("rows") or [])[:20],
    }

