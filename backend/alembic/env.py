"""Alembic 环境。

- URL 从应用配置解析（`app.database.sync_database_url`），支持本地默认 SQLite
  和 `DATABASE_URL` 覆盖；
- SQLite 上必须开 `render_as_batch`，否则 ALTER TABLE 类迁移直接报错；
- `target_metadata` 取自 `Base.metadata`，而 `app.models` 负责把每张表的模块都
  导入进来，autogenerate 才看得到全量表。
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, sync_database_url  # noqa: E402
from app import models  # noqa: E402,F401  确保所有模型已注册

config = context.config

# 默认不接管日志配置：应用启动时会用自己的 JSON 日志（带 request_id），
# 这里再 fileConfig 一次会把根 logger 的 handler 全部替换掉。
# 单独用 alembic CLI 时设 ALEMBIC_CONFIG_LOGGING=1 即可恢复默认行为。
if config.config_file_name is not None and os.getenv("ALEMBIC_CONFIG_LOGGING") == "1":
    fileConfig(config.config_file_name)

url = os.getenv("ALEMBIC_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if not url:
    url = sync_database_url()
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
