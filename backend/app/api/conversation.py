"""对话 API — SSE 流式 + REST。

鉴权与归属：所有会话操作都以 token 里的用户为准，`owner` 不是请求参数，
避免"改个 id 就能读到别人的会话"。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete as sqldel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.config import get_settings
from app.core.errors import AppError
from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.observability.logging import request_id_var
from app.services.audit import record_audit
from app.services.auth import role_has
from app.services.conversation import ConversationService, build_assistant_metadata
from app.services.datasource_context import resolve_datasource_context

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 让 Nginx 不缓冲 SSE
}


def _utc_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


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


# ---------------------------------------------------------------- helpers


async def _owned_conversation(
    db: AsyncSession, conv_id: str, user: User
) -> Conversation:
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id, owner_id=user.id)
    if conv is None:
        # 不区分"不存在"和"不是你的"，避免探测他人会话 id
        raise AppError("conversation_not_found", "对话不存在", status_code=404)
    return conv


async def _resolve_datasources(
    db: AsyncSession, conv: Conversation
) -> tuple[list[str], list[str], list[str]]:
    """返回 (ids, schemas, configs)。schema 优先用缓存，连不上就降级用缓存。"""
    datasource_ids: list[str] = json.loads(conv.datasource_ids) if conv.datasource_ids else []
    resolved = await resolve_datasource_context(db, datasource_ids)
    if resolved[0] and resolved[0] != datasource_ids:
        conv.datasource_ids = json.dumps(resolved[0])
        await db.commit()
    return resolved


def _allow_write(user: User) -> bool:
    return settings_sql_write() and role_has(user.role, "sql:write")


def settings_sql_write() -> bool:
    return get_settings().sql_allow_write_for_admin


async def _begin_turn(
    db: AsyncSession, req: ChatRequest, user: User
) -> tuple[Conversation, ConversationService]:
    svc = ConversationService(db)
    if req.conversation_id:
        conv = await _owned_conversation(db, req.conversation_id, user)
        if conv.title == "新对话" and req.message.strip():
            conv.title = req.message.strip()[:40]
            await db.commit()
    else:
        conv = await svc.create_conversation(user.id, title=req.message.strip()[:40] or "新对话")
    await svc.add_message(conv.id, "user", req.message)
    return conv, svc


def _assistant_metadata(state: dict) -> dict:
    return build_assistant_metadata(state)


# ---------------------------------------------------------------- endpoints


@router.post("/")
async def create_conversation(
    user: User = Depends(require("conversation:write")),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationService(db).create_conversation(user.id)
    return {"id": conv.id, "title": conv.title, "created_at": _utc_iso(conv.created_at)}


@router.get("/")
async def list_conversations(
    user: User = Depends(require("conversation:read")),
    db: AsyncSession = Depends(get_db),
):
    convs = await ConversationService(db).list_conversations(user.id)
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
    user: User = Depends(require("conversation:read")),
    db: AsyncSession = Depends(get_db),
):
    await _owned_conversation(db, conv_id, user)
    msgs = await ConversationService(db).get_messages(conv_id)
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
    user: User = Depends(require("conversation:write")),
    db: AsyncSession = Depends(get_db),
):
    await _owned_conversation(db, conv_id, user)
    await db.execute(sqldel(Message).where(Message.conversation_id == conv_id))
    await db.execute(sqldel(Conversation).where(Conversation.id == conv_id))
    await db.commit()
    await record_audit(db, user_id=user.id, action="conversation_delete", detail={"id": conv_id})
    return {"status": "deleted"}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: User = Depends(require("conversation:write")),
    db: AsyncSession = Depends(get_db),
):
    """与 Agent 对话（非流式）。"""
    conv, svc = await _begin_turn(db, req, user)
    datasource_ids, schemas, configs = await _resolve_datasources(db, conv)
    state = await svc.run_agent(
        conv.id,
        req.message,
        datasource_ids,
        schemas,
        configs,
        allow_write=_allow_write(user),
    )

    if state.get("needs_clarification"):
        question = state.get("clarification_question", "请提供更多信息")
        saved = await svc.add_message(conv.id, "assistant", question)
        return ChatResponse(
            conversation_id=conv.id,
            message_id=saved.id,
            role="assistant",
            content=question,
            needs_clarification=True,
            clarification_question=question,
            clarification_options=state.get("clarification_options", []),
        )

    if state.get("sql_needs_confirmation"):
        sql = state.get("generated_sql", "")
        confirm_msg = f"⚠️ 检测到非只读操作，已拒绝执行：\n\n```sql\n{sql}\n```\n\n本系统只执行只读查询。"
        saved = await svc.add_message(conv.id, "assistant", confirm_msg)
        return ChatResponse(
            conversation_id=conv.id,
            message_id=saved.id,
            role="assistant",
            content=confirm_msg,
            sql_needs_confirmation=True,
        )

    final_response = state.get("final_response", "") or "抱歉，分析过程中出现问题。"
    if state.get("error") and not state.get("final_response"):
        final_response = f"分析出错：{state['error']}"

    metadata = _assistant_metadata(state)
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
    user: User = Depends(require("conversation:write")),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话：节点推进 + 文本 + 元数据，最后落库。"""
    conv, svc = await _begin_turn(db, req, user)
    datasource_ids, schemas, configs = await _resolve_datasources(db, conv)
    request_id = request_id_var.get()

    async def event_stream():
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(event)

        task = asyncio.create_task(
            svc.run_agent(
                conv.id,
                req.message,
                datasource_ids,
                schemas,
                configs,
                allow_write=_allow_write(user),
                on_event=on_event,
            )
        )

        try:
            while True:
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {getter, task}, return_when=asyncio.FIRST_COMPLETED
                )
                if getter in done:
                    event = getter.result()
                    yield _sse(event)
                    continue
                getter.cancel()
                break

            state = await task

            if state.get("needs_clarification"):
                question = state.get("clarification_question", "")
                await svc.add_message(conv.id, "assistant", question)
                yield _sse(
                    {
                        "type": "clarification",
                        "content": question,
                        "options": state.get("clarification_options", []),
                    }
                )
                yield "data: [DONE]\n\n"
                return

            if state.get("sql_needs_confirmation"):
                sql = state.get("generated_sql", "")
                await svc.add_message(
                    conv.id, "assistant", f"⚠️ 检测到非只读操作，已拒绝执行：\n\n```sql\n{sql}\n```"
                )
                yield _sse({"type": "confirm_sql", "sql": sql, "blocked": True})
                yield "data: [DONE]\n\n"
                return

            final = state.get("final_response", "") or "抱歉，分析过程中出现问题。"
            for line in final.split("\n"):
                if line.strip():
                    yield _sse({"type": "text", "content": line + "\n"})
                    await asyncio.sleep(0)  # 让出事件循环，保持打字机效果

            metadata = _assistant_metadata(state)
            await svc.add_message(conv.id, "assistant", final, metadata)
            yield _sse({"type": "metadata", "content": metadata})
            yield "data: [DONE]\n\n"

        except Exception as error:  # noqa: BLE001 - 流内异常必须转成事件
            yield _sse(
                {
                    "type": "error",
                    "content": "分析过程出错，请重试或换个问法",
                    "detail": str(error)[:200],
                    "request_id": request_id,
                }
            )
            yield "data: [DONE]\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )
