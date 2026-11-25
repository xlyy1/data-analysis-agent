"""项目路径解析。

所有需要落盘的位置（元数据库、上传文件、清洗后的数据、追踪库）都从这里取，
避免散落的 `..` 相对路径在不同启动目录下算出不同的结果。
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/app/paths.py -> backend/app -> backend -> <repo>
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
# 容器里用 DATA_DIR 指到挂载卷（默认 /app/data），本机不设则落在 <repo>/data
DATA_DIR = Path(os.getenv("DATA_DIR") or (REPO_ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
INGEST_DIR = DATA_DIR / "ingested"
SAMPLE_DIR = DATA_DIR / "samples"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_from_backend(value: str | Path) -> Path:
    """把相对路径按 backend/ 解析成绝对路径；绝对路径原样返回。"""
    path = Path(value)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()
