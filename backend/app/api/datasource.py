"""数据源管理 API：CRUD + 连接测试 + schema/画像刷新 + 上传清洗 + 增量重导。

安全边界：
- 连接配置里的密码永远不会出现在响应里（`_redact`）；
- 上传文件名不参与落盘路径（用 uuid），避免 `../../etc/passwd` 型路径穿越；
- 上传有大小上限且按块读取，超限立刻中断，不会先把 1GB 读进内存；
- 写操作只对 admin / analyst 开放，viewer 只能读列表和 schema。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.config import get_settings
from app.core.errors import AppError
from app.database import get_db
from app.datasource.factory import REQUIRED_FIELDS, SUPPORTED_TYPES, create_datasource
from app.models.datasource import DataSource
from app.models.user import ROLE_ADMIN, User
from app.paths import INGEST_DIR, UPLOAD_DIR, ensure_dir
from app.services.audit import record_audit
from app.services.ingest import SUPPORTED_SUFFIXES, file_digest, ingest_bytes, safe_table_name
from app.services.profiling import profile_datasource
from app.services.schema import describe_schema, invalidate_schema_cache

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

SECRET_KEYS = {"password", "passwd", "pwd", "secret", "token", "api_key"}
CHUNK = 256 * 1024


def _utc_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _redact(config: dict) -> dict:
    return {
        key: ("******" if key.lower() in SECRET_KEYS and value else value)
        for key, value in config.items()
    }


def _scrub(text: str, config: dict | None = None) -> str:
    """错误信息里可能夹带连接串，把密码值替换掉再对外返回。"""
    cleaned = str(text)
    for key, value in (config or {}).items():
        if key.lower() in SECRET_KEYS and value:
            cleaned = cleaned.replace(str(value), "******")
    return cleaned[:200]


def _config_of(ds: DataSource) -> dict:
    return json.loads(ds.config) if isinstance(ds.config, str) else (ds.config or {})


def _table_count(ds: DataSource) -> int:
    if not ds.table_schema:
        return 0
    try:
        return len(json.loads(ds.table_schema).get("tables", []))
    except (json.JSONDecodeError, AttributeError):
        return 0


def _row_count(ds: DataSource) -> int:
    if not ds.table_schema:
        return 0
    try:
        return sum(int(t.get("row_count") or 0) for t in json.loads(ds.table_schema).get("tables", []))
    except (json.JSONDecodeError, AttributeError):
        return 0


def _public(ds: DataSource, *, detail: bool = False) -> dict:
    payload = {
        "id": ds.id,
        "name": ds.name,
        "type": ds.type,
        "owner_id": ds.owner_id,
        "is_active": bool(ds.is_active),
        "table_count": _table_count(ds),
        "row_count": _row_count(ds),
        "created_at": _utc_iso(ds.created_at),
        "updated_at": _utc_iso(ds.updated_at),
        "config": _redact(_config_of(ds)),
        "seeded": bool(_config_of(ds).get("seeded")),
    }
    if detail:
        payload["schema"] = json.loads(ds.table_schema) if ds.table_schema else None
        payload["profile"] = json.loads(ds.profile_json) if ds.profile_json else None
    return payload


async def _visible(ds_id: str, user: User, db: AsyncSession) -> DataSource:
    ds = (await db.execute(select(DataSource).where(DataSource.id == ds_id))).scalar_one_or_none()
    if ds is None or not ds.is_active:
        raise AppError("datasource_not_found", "数据源不存在", status_code=404)
    if user.role == ROLE_ADMIN:
        return ds
    if ds.owner_id == user.id or _config_of(ds).get("seeded"):
        return ds
    raise AppError("datasource_not_found", "数据源不存在", status_code=404)


async def _writable(ds_id: str, user: User, db: AsyncSession) -> DataSource:
    ds = await _visible(ds_id, user, db)
    if user.role != ROLE_ADMIN and ds.owner_id != user.id:
        raise AppError("forbidden", "只能修改自己创建的数据源", status_code=403)
    return ds


def _validate_config(ds_type: str, config: dict) -> None:
    if ds_type not in SUPPORTED_TYPES:
        raise AppError(
            "unsupported_type",
            f"不支持的数据源类型：{ds_type}",
            status_code=400,
            details={"supported": list(SUPPORTED_TYPES)},
        )
    missing = [key for key in REQUIRED_FIELDS.get(ds_type, ()) if not config.get(key)]
    if missing:
        raise AppError(
            "invalid_config",
            f"缺少必填配置：{', '.join(missing)}",
            status_code=400,
            details={"missing": missing},
        )
    if ds_type == "sqlite":
        path = Path(config["db_path"])
        if not path.exists():
            raise AppError("invalid_config", f"SQLite 文件不存在：{path}", status_code=400)


async def _refresh_schema(db: AsyncSession, ds: DataSource, *, with_profile: bool = False) -> dict:
    connector = create_datasource(ds.type, _config_of(ds))
    await connector.connect()
    try:
        schema = await describe_schema(connector, use_cache=False)
        if with_profile:
            profile = await profile_datasource(connector)
            ds.profile_json = json.dumps(profile, ensure_ascii=False, default=str)
    finally:
        await connector.disconnect()
    ds.table_schema = json.dumps(schema, ensure_ascii=False, default=str)
    invalidate_schema_cache()
    await db.commit()
    return schema


# ------------------------------------------------------------------ schemas


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: str
    config: dict


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict | None = None


# ------------------------------------------------------------------ endpoints


@router.get("/supported-types")
async def supported_types(_: User = Depends(require("datasource:read"))):
    return {
        "types": [
            {"type": "sqlite", "label": "SQLite 文件", "fields": ["db_path"]},
            {"type": "mysql", "label": "MySQL", "fields": ["host", "port", "user", "password", "database"]},
            {"type": "postgres", "label": "PostgreSQL", "fields": ["host", "port", "user", "password", "database"]},
            {"type": "excel", "label": "Excel 文件", "fields": ["file_path"], "upload": True},
            {"type": "csv", "label": "CSV 文件", "fields": ["file_path"], "upload": True},
        ],
        "max_upload_mb": get_settings().max_upload_mb,
    }


@router.get("")
async def list_datasources(
    user: User = Depends(require("datasource:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(DataSource)
            .where(DataSource.is_active == True)  # noqa: E712
            .order_by(DataSource.created_at)
        )
    ).scalars().all()
    if user.role != ROLE_ADMIN:
        rows = [ds for ds in rows if ds.owner_id == user.id or _config_of(ds).get("seeded")]
    return {"items": [_public(ds) for ds in rows]}


@router.post("", status_code=201)
async def create_datasource_endpoint(
    payload: DataSourceCreate,
    user: User = Depends(require("datasource:write")),
    db: AsyncSession = Depends(get_db),
):
    _validate_config(payload.type, payload.config)
    ds = DataSource(
        name=payload.name,
        type=payload.type,
        config=json.dumps(payload.config, ensure_ascii=False),
        owner_id=user.id,
    )
    db.add(ds)
    await db.commit()

    started = time.perf_counter()
    try:
        await _refresh_schema(db, ds, with_profile=True)
    except Exception as error:  # noqa: BLE001 - 建连失败要回滚数据源
        ds.is_active = False
        await db.commit()
        raise AppError(
            "connection_failed",
            f"连接数据源失败：{type(error).__name__}",
            status_code=400,
            details={"reason": _scrub(error, payload.config)},
        ) from error

    await db.refresh(ds)
    await record_audit(
        db,
        user_id=user.id,
        action="datasource_create",
        detail={"id": ds.id, "type": ds.type, "latency_ms": round((time.perf_counter() - started) * 1000, 1)},
    )
    return _public(ds, detail=True)


@router.post("/test")
async def test_connection(
    payload: DataSourceCreate,
    _: User = Depends(require("datasource:write")),
):
    """不落库，先试连一次——前端"测试连接"按钮用。"""
    _validate_config(payload.type, payload.config)
    started = time.perf_counter()
    try:
        connector = create_datasource(payload.type, payload.config)
        await connector.connect()
        tables = await connector.get_tables()
        await connector.disconnect()
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "message": f"连接失败：{type(error).__name__}",
            "detail": _scrub(error, payload.config),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    return {
        "ok": True,
        "message": f"连接成功，发现 {len(tables)} 张表",
        "tables": [{"name": t.name, "columns": len(t.columns), "row_count": t.row_count} for t in tables[:50]],
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(require("datasource:write")),
    db: AsyncSession = Depends(get_db),
    append: bool = Query(default=False, description="重复上传时是否增量追加（按行哈希去重）"),
):
    settings = get_settings()
    if not file.filename:
        raise AppError("invalid_upload", "文件名不能为空", status_code=400)

    original_name = Path(file.filename).name
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise AppError(
            "invalid_upload",
            f"仅支持 {', '.join(sorted(SUPPORTED_SUFFIXES))} 文件",
            status_code=400,
        )

    limit = settings.max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AppError(
                "upload_too_large",
                f"文件超过 {settings.max_upload_mb} MB 上限",
                status_code=413,
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise AppError("invalid_upload", "文件内容为空", status_code=400)

    ensure_dir(UPLOAD_DIR)
    ensure_dir(INGEST_DIR)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(content)

    ds_id = str(uuid.uuid4())
    ingest_db = INGEST_DIR / f"{ds_id}.db"
    table = safe_table_name(original_name)
    try:
        result = ingest_bytes(
            content, original_name, db_path=ingest_db, table=table, append=append
        )
    except Exception as error:  # noqa: BLE001
        stored_path.unlink(missing_ok=True)
        ingest_db.unlink(missing_ok=True)
        raise AppError(
            "ingest_failed",
            f"文件解析失败：{type(error).__name__}",
            status_code=400,
            details={"reason": _scrub(error)},
        ) from error

    ds_type = "csv" if suffix == ".csv" else "excel"
    config = {
        "file_name": original_name,
        "file_path": str(stored_path),
        "ingested_db": str(ingest_db),
        "table": result.table,
        "source_sha256": file_digest(content),
        "rows": result.rows_in,
        "cleaning": {
            "dropped_blank": result.dropped_blank,
            "dropped_duplicate": result.dropped_duplicate,
            "notes": result.notes,
            "encoding": result.encoding,
            "sheet": result.sheet,
        },
    }
    ds = DataSource(
        id=ds_id,
        name=original_name,
        type=ds_type,
        config=json.dumps(config, ensure_ascii=False),
        owner_id=user.id,
    )
    db.add(ds)
    await db.commit()
    await _refresh_schema(db, ds, with_profile=True)
    await db.refresh(ds)

    await record_audit(
        db,
        user_id=user.id,
        action="datasource_upload",
        detail={"id": ds.id, "rows": result.rows_in, "type": ds_type, "size": total},
    )
    return {**_public(ds, detail=True), "ingest": result.as_dict()}


@router.get("/{ds_id}")
async def get_datasource(
    ds_id: str,
    user: User = Depends(require("datasource:read")),
    db: AsyncSession = Depends(get_db),
):
    ds = await _visible(ds_id, user, db)
    return _public(ds, detail=True)


@router.patch("/{ds_id}")
async def update_datasource(
    ds_id: str,
    payload: DataSourceUpdate,
    user: User = Depends(require("datasource:write")),
    db: AsyncSession = Depends(get_db),
):
    ds = await _writable(ds_id, user, db)
    if payload.name:
        ds.name = payload.name
    if payload.config is not None:
        config = _config_of(ds)
        for key, value in payload.config.items():
            # 密码字段传 ****** 表示"不修改"
            if key.lower() in SECRET_KEYS and value in ("", "******"):
                continue
            config[key] = value
        _validate_config(ds.type, config)
        ds.config = json.dumps(config, ensure_ascii=False)
    await db.commit()
    try:
        await _refresh_schema(db, ds)
    except Exception as error:  # noqa: BLE001
        raise AppError(
            "connection_failed",
            f"配置已保存，但重新连接失败：{type(error).__name__}",
            status_code=400,
        ) from error
    await record_audit(db, user_id=user.id, action="datasource_update", detail={"id": ds.id})
    await db.refresh(ds)
    return _public(ds, detail=True)


@router.delete("/{ds_id}")
async def delete_datasource(
    ds_id: str,
    user: User = Depends(require("datasource:write")),
    db: AsyncSession = Depends(get_db),
):
    ds = await _writable(ds_id, user, db)
    ds.is_active = False
    await db.commit()
    await record_audit(db, user_id=user.id, action="datasource_delete", detail={"id": ds.id})
    return {"status": "deleted"}


@router.post("/{ds_id}/test")
async def test_existing(
    ds_id: str,
    user: User = Depends(require("datasource:read")),
    db: AsyncSession = Depends(get_db),
):
    ds = await _visible(ds_id, user, db)
    started = time.perf_counter()
    try:
        connector = create_datasource(ds.type, _config_of(ds))
        await connector.connect()
        tables = await connector.get_tables()
        await connector.disconnect()
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "message": f"连接失败：{type(error).__name__}",
            "detail": _scrub(error, _config_of(ds)),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    return {
        "ok": True,
        "message": f"连接正常，{len(tables)} 张表",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@router.post("/{ds_id}/refresh-schema")
async def refresh_schema(
    ds_id: str,
    user: User = Depends(require("datasource:write")),
    db: AsyncSession = Depends(get_db),
    with_profile: bool = Query(default=True),
):
    ds = await _writable(ds_id, user, db)
    schema = await _refresh_schema(db, ds, with_profile=with_profile)
    return {"schema": schema, "profile": json.loads(ds.profile_json) if ds.profile_json else None}


@router.get("/{ds_id}/profile")
async def get_profile(
    ds_id: str,
    user: User = Depends(require("datasource:read")),
    db: AsyncSession = Depends(get_db),
    refresh: bool = Query(default=False),
):
    ds = await _visible(ds_id, user, db)
    if ds.profile_json and not refresh:
        return json.loads(ds.profile_json)
    connector = create_datasource(ds.type, _config_of(ds))
    await connector.connect()
    try:
        profile = await profile_datasource(connector)
    finally:
        await connector.disconnect()
    ds.profile_json = json.dumps(profile, ensure_ascii=False, default=str)
    await db.commit()
    return profile


@router.post("/{ds_id}/reingest")
async def reingest(
    ds_id: str,
    user: User = Depends(require("datasource:write")),
    db: AsyncSession = Depends(get_db),
    append: bool = Query(default=True),
):
    """重新解析原始文件，增量追加（默认）或整表覆盖。"""
    ds = await _writable(ds_id, user, db)
    config = _config_of(ds)
    path = config.get("file_path")
    if not path or not Path(path).exists():
        raise AppError(
            "no_source_file",
            "该数据源没有可重导的原始文件（只支持上传类数据源）",
            status_code=400,
        )
    ingest_db = Path(config.get("ingested_db") or INGEST_DIR / f"{ds.id}.db")
    table = config.get("table") or safe_table_name(config.get("file_name", "data"))
    result = ingest_bytes(
        Path(path).read_bytes(),
        config.get("file_name", "data.csv"),
        db_path=ingest_db,
        table=table,
        append=append,
    )
    config["ingested_db"] = str(ingest_db)
    config["table"] = table
    config.setdefault("cleaning", {})
    config["cleaning"] = {
        "dropped_blank": result.dropped_blank,
        "dropped_duplicate": result.dropped_duplicate,
        "notes": result.notes,
        "encoding": result.encoding,
        "sheet": result.sheet,
    }
    ds.config = json.dumps(config, ensure_ascii=False)
    await db.commit()
    await _refresh_schema(db, ds, with_profile=True)
    await db.refresh(ds)
    await record_audit(
        db,
        user_id=user.id,
        action="datasource_reingest",
        detail={"id": ds.id, "append": append, "rows": result.rows_in},
    )
    return {"ingest": result.as_dict(), "datasource": _public(ds, detail=True)}
