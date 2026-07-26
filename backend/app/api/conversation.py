"""对话 API — SSE 流式 + REST"""

import json
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

# Helper: make datetime ISO strings explicitly UTC so JS Date() parses correctly
def _utc_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.services.conversation import ConversationService
from app.models.conversation import Conversation, Message

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

DEFAULT_USER = "default"


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    role: str
    content: str
    metadata: dict | None = None
    needs_clarification: bool = False
    clarification_question: str = ""
    clarification_options: list[str] = []
    sql_needs_confirmation: bool = False


@router.post("/")
async def create_conversation(
    db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    conv = await svc.create_conversation(DEFAULT_USER)
    return {"id": conv.id, "title": conv.title, "created_at": _utc_iso(conv.created_at)}


@router.get("/")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    convs = await svc.list_conversations(DEFAULT_USER)
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": _utc_iso(c.created_at),
            "updated_at": _utc_iso(c.updated_at),
        }
        for c in convs
    ]


@router.get("/{conv_id}/messages")
async def get_messages(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    msgs = await svc.get_messages(conv_id)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "metadata": json.loads(m.metadata_json) if m.metadata_json else None,
            "created_at": _utc_iso(m.created_at),
        }
        for m in msgs
    ]


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and its messages"""
    from sqlalchemy import delete as sqldel
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    await db.execute(sqldel(Message).where(Message.conversation_id == conv_id))
    await db.execute(sqldel(Conversation).where(Conversation.id == conv_id))
    await db.commit()
    return {"status": "deleted"}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """与 Agent 对话（非流式）"""
    svc = ConversationService(db)

    # 创建或获取对话
    if req.conversation_id:
        conv = await svc.get_conversation(req.conversation_id)
        if not conv:
            raise HTTPException(404, "对话不存在")
        # Auto-name the conversation from the first real question
        if conv.title == "新对话" and len(req.message.strip()) > 0:
            conv.title = req.message.strip()[:40]
            await db.commit()
    else:
        conv = await svc.create_conversation(DEFAULT_USER, title=req.message.strip()[:40] if req.message.strip() else "新对话")

    # 保存用户消息
    await svc.add_message(conv.id, "user", req.message)

    # 自动关联所有活跃数据源
    datasource_ids = json.loads(conv.datasource_ids) if conv.datasource_ids else []
    if not datasource_ids:
        from sqlalchemy import select
        from app.models.datasource import DataSource
        result = await db.execute(
            select(DataSource.id).where(DataSource.is_active == True)
        )
        all_ids = [row[0] for row in result.all()]
        if all_ids:
            datasource_ids = all_ids
            conv.datasource_ids = json.dumps(all_ids)
            await db.commit()
    schemas = []
    configs = []
    if datasource_ids:
        from sqlalchemy import select
        from app.models.datasource import DataSource
        from app.datasource.factory import create_datasource as ds_factory
        result = await db.execute(
            select(DataSource).where(DataSource.id.in_(datasource_ids), DataSource.is_active == True)
        )
        active_sources = result.scalars().all()
        for ds in active_sources:
            cfg_dict = json.loads(ds.config) if isinstance(ds.config, str) else ds.config
            configs.append(json.dumps({"type": ds.type, "config": cfg_dict}, ensure_ascii=False))

            # Connect to compute real schema (with total columns injected)
            try:
                connector = ds_factory(ds.type, cfg_dict)
                await connector.connect()

                # Auto-compute total columns BEFORE generating schema for LLM
                if hasattr(connector, "auto_add_total_columns"):
                    connector.auto_add_total_columns()

                tables = await connector.get_tables()
                await connector.disconnect()

                schema_obj = {
                    "tables": [
                        {
                            "name": t.name,
                            "columns": [{"name": c.name, "dtype": c.dtype} for c in t.columns],
                            "row_count": t.row_count,
                        }
                        for t in tables
                    ]
                }
                # Cache updated schema
                ds.table_schema = json.dumps(schema_obj, ensure_ascii=False)
                await db.commit()
                schemas.append(json.dumps(schema_obj, ensure_ascii=False))
            except Exception:
                # Fallback to cached schema
                if ds.table_schema:
                    schemas.append(json.dumps(json.loads(ds.table_schema), ensure_ascii=False))

    # 运行 Agent
    state = await svc.run_agent(conv.id, req.message, datasource_ids, schemas, configs)

    # 处理澄清场景
    if state.get("needs_clarification"):
        clarification_msg = state.get("clarification_question", "请提供更多信息")
        saved = await svc.add_message(conv.id, "assistant", clarification_msg)
        return ChatResponse(
            conversation_id=conv.id,
            message_id=saved.id,
            role="assistant",
            content=clarification_msg,
            needs_clarification=True,
            clarification_question=clarification_msg,
            clarification_options=state.get("clarification_options", []),
        )

    # 处理 SQL 确认场景
    if state.get("sql_needs_confirmation"):
        sql = state.get("generated_sql", "")
        confirm_msg = f"⚠️ 检测到非 SELECT 操作，请确认是否执行：\n\n```sql\n{sql}\n```"
        saved = await svc.add_message(conv.id, "assistant", confirm_msg)
        return ChatResponse(
            conversation_id=conv.id,
            message_id=saved.id,
            role="assistant",
            content=confirm_msg,
            sql_needs_confirmation=True,
        )

    # 正常回复
    final_response = state.get("final_response", "抱歉，分析过程中出现问题。")
    error = state.get("error", "")
    if error:
        final_response = f"分析出错：{error}"

    # 保存助手消息（含元数据）
    metadata = {
        "sql": state.get("generated_sql", ""),
        "sql_explanation": state.get("sql_explanation", ""),
        "analysis_type": state.get("analysis_type", ""),
        "chart_config": json.loads(state.get("chart_config_json", "{}")),
        "diagnosis_causes": state.get("diagnosis_causes", []),
        "diagnosis_suggestions": state.get("diagnosis_suggestions", []),
    }
    saved = await svc.add_message(conv.id, "assistant", final_response, metadata)

    return ChatResponse(
        conversation_id=conv.id,
        message_id=saved.id,
        role="assistant",
        content=final_response,
        metadata=metadata,
    )


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话"""
    svc = ConversationService(db)

    if req.conversation_id:
        conv = await svc.get_conversation(req.conversation_id)
        if not conv:
            raise HTTPException(404, "对话不存在")
    else:
        conv = await svc.create_conversation(DEFAULT_USER, title=req.message[:30])

    await svc.add_message(conv.id, "user", req.message)

    # Load schemas
    datasource_ids = json.loads(conv.datasource_ids) if conv.datasource_ids else []
    if not datasource_ids:
        from sqlalchemy import select
        from app.models.datasource import DataSource
        result = await db.execute(
            select(DataSource.id).where(DataSource.is_active == True)
        )
        all_ids = [row[0] for row in result.all()]
        if all_ids:
            datasource_ids = all_ids
            conv.datasource_ids = json.dumps(all_ids)
            await db.commit()
    schemas = []
    configs = []
    if datasource_ids:
        from sqlalchemy import select
        from app.models.datasource import DataSource
        from app.datasource.factory import create_datasource as ds_factory
        result = await db.execute(
            select(DataSource).where(DataSource.id.in_(datasource_ids), DataSource.is_active == True)
        )
        for ds in result.scalars().all():
            cfg_dict = json.loads(ds.config) if isinstance(ds.config, str) else ds.config
            configs.append(json.dumps({"type": ds.type, "config": cfg_dict}, ensure_ascii=False))
            try:
                connector = ds_factory(ds.type, cfg_dict)
                await connector.connect()
                if hasattr(connector, "auto_add_total_columns"):
                    connector.auto_add_total_columns()
                tables = await connector.get_tables()
                await connector.disconnect()
                schema_obj = {"tables": [{"name": t.name, "columns": [{"name": c.name, "dtype": c.dtype} for c in t.columns], "row_count": t.row_count} for t in tables]}
                ds.table_schema = json.dumps(schema_obj, ensure_ascii=False)
                await db.commit()
                schemas.append(json.dumps(schema_obj, ensure_ascii=False))
            except Exception:
                if ds.table_schema:
                    schemas.append(json.dumps(json.loads(ds.table_schema), ensure_ascii=False))

    async def event_stream():
        try:
            state = await svc.run_agent(conv.id, req.message, datasource_ids, schemas, configs)

            if state.get("needs_clarification"):
                msg = state.get("clarification_question", "")
                yield f"data: {json.dumps({'type': 'clarification', 'content': msg, 'options': state.get('clarification_options', [])})}\n\n"
                return

            if state.get("sql_needs_confirmation"):
                sql = state.get("generated_sql", "")
                yield f"data: {json.dumps({'type': 'confirm_sql', 'sql': sql})}\n\n"
                return

            # 流式输出最终回复
            final = state.get("final_response", "")
            # 模拟流式：按句子切分
            sentences = final.replace("\n\n", "\n").split("\n")
            for sentence in sentences:
                if sentence.strip():
                    yield f"data: {json.dumps({'type': 'text', 'content': sentence + '\n'})}\n\n"
                    await asyncio.sleep(0.05)

            # 发送元数据
            metadata = {
                "sql": state.get("generated_sql", ""),
                "chart_config": json.loads(state.get("chart_config_json", "{}")),
            }
            yield f"data: {json.dumps({'type': 'metadata', 'content': metadata})}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
