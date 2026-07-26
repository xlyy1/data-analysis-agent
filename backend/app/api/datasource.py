"""数据源管理 API"""

import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

def _utc_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.datasource import DataSource
from app.datasource.factory import create_datasource

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

DEFAULT_OWNER = "default"


class DataSourceCreate(BaseModel):
    name: str
    type: str  # excel | csv | mysql | postgres | sqlite
    config: dict  # 连接配置


@router.post("/")
async def create_datasource_endpoint(
    ds: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
):
    datasource = DataSource(
        name=ds.name,
        type=ds.type,
        config=json.dumps(ds.config),
        owner_id=DEFAULT_OWNER,
    )
    db.add(datasource)
    await db.commit()
    return {"id": datasource.id, "name": datasource.name, "type": datasource.type}


@router.get("/")
async def list_datasources(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DataSource).where(DataSource.is_active == True)
    )
    sources = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "type": s.type,
            "created_at": _utc_iso(s.created_at),
        }
        for s in sources
    ]


@router.get("/{ds_id}/schema")
async def get_schema(
    ds_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DataSource).where(DataSource.id == ds_id))
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(404, "数据源不存在")

    # 如果已缓存 schema 则直接返回
    if ds.table_schema:
        return json.loads(ds.table_schema)

    # 否则连接获取
    try:
        connector = create_datasource(ds.type, ds.config)
        await connector.connect()
        tables = await connector.get_tables()
        await connector.disconnect()

        schema = {
            "tables": [
                {
                    "name": t.name,
                    "columns": [{"name": c.name, "dtype": c.dtype} for c in t.columns],
                    "row_count": t.row_count,
                }
                for t in tables
            ]
        }
        # 缓存
        ds.table_schema = json.dumps(schema)
        await db.commit()
        return schema
    except Exception as e:
        raise HTTPException(500, f"获取 schema 失败: {e}")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 Excel/CSV 文件作为数据源"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    suffix = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ("xlsx", "xls", "csv"):
        raise HTTPException(400, "仅支持 .xlsx / .xls / .csv 文件")

    content = await file.read()

    # Save to persistent uploads directory
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    save_path = os.path.join(uploads_dir, file.filename)
    with open(save_path, "wb") as f:
        f.write(content)

    ds_type = "csv" if suffix == "csv" else "excel"
    config = {"file_name": file.filename, "file_path": save_path}
    datasource = DataSource(
        name=file.filename,
        type=ds_type,
        config=json.dumps(config),
        owner_id=DEFAULT_OWNER,
    )
    db.add(datasource)
    await db.commit()

    # 立即解析 schema
    from app.datasource.excel import ExcelDataSource

    excel_ds = ExcelDataSource(file_path=save_path, file_name=file.filename)
    await excel_ds.connect()
    tables = await excel_ds.get_tables()
    await excel_ds.disconnect()

    schema = {
        "tables": [
            {
                "name": t.name,
                "columns": [{"name": c.name, "dtype": c.dtype} for c in t.columns],
                "row_count": t.row_count,
            }
            for t in tables
        ]
    }
    datasource.table_schema = json.dumps(schema)
    await db.commit()

    return {
        "id": datasource.id,
        "name": datasource.name,
        "type": datasource.type,
        "schema": schema,
    }


@router.delete("/{ds_id}")
async def delete_datasource(
    ds_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DataSource).where(DataSource.id == ds_id))
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(404, "数据源不存在")

    ds.is_active = False
    await db.commit()
    return {"status": "deleted"}
