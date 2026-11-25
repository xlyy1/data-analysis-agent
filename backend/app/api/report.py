"""报告 API：从对话生成报告，落库后可按 id 反复下载。

`format=json` 返回结构化元信息 + 下载链接（前端用）；
其它 format 直接返回文件流（命令行 / curl 用）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.core.errors import AppError
from app.database import get_db
from app.models.report import Report
from app.models.user import ROLE_ADMIN, User
from app.services.audit import record_audit
from app.services.conversation import ConversationService
from app.services.report import ReportService

router = APIRouter(prefix="/api/reports", tags=["reports"])

MEDIA_TYPES = {
    "markdown": ("text/markdown; charset=utf-8", "md"),
    "html": ("text/html; charset=utf-8", "html"),
    "pdf": ("application/pdf", "pdf"),
}


def _utc_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class ReportRequest(BaseModel):
    conversation_id: str
    format: str = Field(default="markdown", pattern="^(markdown|html|pdf|json)$")
    title: str | None = None


def _render(report: Report, fmt: str) -> Response:
    if fmt == "markdown":
        media, ext = MEDIA_TYPES["markdown"]
        return Response(
            report.markdown,
            media_type=media,
            headers={"Content-Disposition": f'inline; filename="report-{report.id[:8]}.{ext}"'},
        )
    if fmt == "html":
        media, ext = MEDIA_TYPES["html"]
        return Response(
            ReportService.generate_html(report.markdown),
            media_type=media,
            headers={"Content-Disposition": f'inline; filename="report-{report.id[:8]}.{ext}"'},
        )
    media, ext = MEDIA_TYPES["pdf"]
    html = ReportService.generate_html(report.markdown)
    return Response(
        ReportService.generate_pdf(html),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="report-{report.id[:8]}.{ext}"'
        },
    )


async def _build_markdown(db: AsyncSession, conversation_id: str, user: User) -> tuple[Report, object]:
    svc = ConversationService(db)
    conv = await svc.get_conversation(conversation_id, owner_id=user.id)
    if conv is None:
        raise AppError("conversation_not_found", "对话不存在", status_code=404)

    messages = await svc.get_messages(conversation_id)
    user_questions = [m.content for m in messages if m.role == "user"]
    assistant_msgs = [m for m in messages if m.role == "assistant"]

    question = user_questions[-1] if user_questions else ""
    analysis_parts: list[str] = []
    causes: list[str] = []
    suggestions: list[str] = []
    sql = ""
    data_columns: list[str] = []
    data_rows: list[list] = []

    for msg in assistant_msgs:
        if msg.metadata_json:
            meta = json.loads(msg.metadata_json)
            sql = meta.get("sql") or sql
            causes = meta.get("diagnosis_causes") or causes
            suggestions = meta.get("diagnosis_suggestions") or suggestions
            if meta.get("data_columns"):
                data_columns = meta["data_columns"]
                data_rows = meta.get("data_rows") or []
        analysis_parts.append(msg.content)

    markdown = ReportService.generate_markdown(
        question,
        "\n".join(analysis_parts),
        causes,
        suggestions,
        sql,
        data_columns,
        data_rows,
    )
    return markdown, conv


@router.post("/generate")
async def generate_report(
    req: ReportRequest,
    user: User = Depends(require("report:generate")),
    db: AsyncSession = Depends(get_db),
):
    markdown, conv = await _build_markdown(db, req.conversation_id, user)
    report = Report(
        user_id=user.id,
        conversation_id=req.conversation_id,
        title=req.title or f"{conv.title} 分析报告",
        question=conv.title,
        sql="",
        markdown=markdown,
    )
    db.add(report)
    await db.commit()
    await record_audit(
        db,
        user_id=user.id,
        action="report_generate",
        detail={"report_id": report.id, "format": req.format, "conversation_id": req.conversation_id},
    )

    if req.format == "json":
        return {
            "id": report.id,
            "title": report.title,
            "created_at": _utc_iso(report.created_at),
            "markdown_preview": report.markdown[:600],
            "download": {
                fmt: f"/api/reports/{report.id}/download?format={fmt}"
                for fmt in ("markdown", "html", "pdf")
            },
        }
    return _render(report, req.format)


@router.get("")
async def list_reports(
    user: User = Depends(require("report:read")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
):
    stmt = select(Report).order_by(Report.created_at.desc()).limit(limit)
    if user.role != ROLE_ADMIN:
        stmt = stmt.where(Report.user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "conversation_id": r.conversation_id,
                "created_at": _utc_iso(r.created_at),
            }
            for r in rows
        ]
    }


async def _owned_report(report_id: str, user: User, db: AsyncSession) -> Report:
    report = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
    if report is None or (user.role != ROLE_ADMIN and report.user_id != user.id):
        raise AppError("report_not_found", "报告不存在", status_code=404)
    return report


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    user: User = Depends(require("report:read")),
    db: AsyncSession = Depends(get_db),
):
    report = await _owned_report(report_id, user, db)
    return {
        "id": report.id,
        "title": report.title,
        "conversation_id": report.conversation_id,
        "created_at": _utc_iso(report.created_at),
        "markdown": report.markdown,
    }


@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    user: User = Depends(require("report:read")),
    db: AsyncSession = Depends(get_db),
    format: str = Query(default="markdown", pattern="^(markdown|html|pdf)$"),
):
    report = await _owned_report(report_id, user, db)
    return _render(report, format)


@router.delete("/{report_id}")
async def delete_report(
    report_id: str,
    user: User = Depends(require("report:generate")),
    db: AsyncSession = Depends(get_db),
):
    report = await _owned_report(report_id, user, db)
    await db.delete(report)
    await db.commit()
    return {"status": "deleted"}
