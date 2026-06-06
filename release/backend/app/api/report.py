"""报告 API"""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.services.report import ReportService
from app.services.conversation import ConversationService

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportRequest(BaseModel):
    conversation_id: str
    format: str = "markdown"  # markdown | html | pdf


@router.post("/generate")
async def generate_report(
    req: ReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """从对话生成报告"""
    svc = ConversationService(db)
    conv = await svc.get_conversation(req.conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    messages = await svc.get_messages(req.conversation_id)

    # 提取信息
    user_questions = [m.content for m in messages if m.role == "user"]
    assistant_msgs = [m for m in messages if m.role == "assistant"]

    question = user_questions[-1] if user_questions else ""
    analysis = ""
    causes = []
    suggestions = []
    sql = ""
    data_columns = []
    data_rows = []

    for msg in assistant_msgs:
        if msg.metadata_json:
            meta = json.loads(msg.metadata_json)
            sql = meta.get("sql", sql)
            causes = meta.get("diagnosis_causes", causes)
            suggestions = meta.get("diagnosis_suggestions", suggestions)
        analysis += msg.content + "\n"

    if req.format == "markdown":
        content = ReportService.generate_markdown(question, analysis, causes, suggestions, sql, data_columns, data_rows)
        return Response(content, media_type="text/markdown; charset=utf-8")
    elif req.format == "html":
        md = ReportService.generate_markdown(question, analysis, causes, suggestions, sql, data_columns, data_rows)
        html = ReportService.generate_html(md)
        return Response(html, media_type="text/html; charset=utf-8")
    elif req.format == "pdf":
        md = ReportService.generate_markdown(question, analysis, causes, suggestions, sql, data_columns, data_rows)
        html = ReportService.generate_html(md)
        pdf_bytes = ReportService.generate_pdf(html)
        return Response(pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=report.pdf"})
    else:
        raise HTTPException(400, "不支持的格式，可选: markdown, html, pdf")
