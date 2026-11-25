"""应用配置 — 通过 pydantic-settings 加载 .env

约定：所有可调参数都在这里集中，代码里不允许再出现魔法数字。
CI / 单测通过环境变量覆盖（见 backend/tests/conftest.py），不依赖任何付费 Key。
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- 运行环境 ---
    app_env: str = "dev"  # dev | test | prod
    debug: bool = False

    # --- LLM ---
    llm_provider: str = "deepseek"  # deepseek | ollama | openai | mock

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_temperature: float = 0.1  # 评测时建议设为 0，保证结果可复现
    # 单次模型调用的硬超时（外层 TimedLLM 强制生效，不依赖 SDK 自己的默认值）
    llm_request_timeout_seconds: float = 45.0
    llm_max_retries: int = 1

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # --- 数据库 ---
    # 留空 = 用 <repo>/data/agent.db；也可直接给 sqlite+aiosqlite:///... 或 postgresql+asyncpg://...
    database_url: str = ""

    # --- 服务 ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "*"  # 逗号分隔

    # --- 认证 / 权限 ---
    # 生产必须通过环境变量提供；默认值仅用于本地演示，启动时会打 warning
    auth_secret_key: str = "dev-only-change-me-in-production"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin12345"
    login_rate_limit_per_minute: int = 10

    # --- 沙箱 ---
    sandbox_timeout: int = 30

    # --- 查询限制 ---
    max_query_rows: int = 100_000
    max_return_rows: int = 10_000

    # --- SQL 安全策略（只读 / 限流 / 超时 / 行数上限）---
    sql_max_chars: int = 8000
    sql_default_limit: int = 1000  # 没有 LIMIT 的 SELECT 自动补这个上限
    sql_allow_write_for_admin: bool = False  # 默认全只读，写操作一律拒绝
    sql_statement_timeout_seconds: float = 15.0
    sql_rate_limit_per_minute: int = 60
    sql_max_result_cells: int = 200_000

    # --- SQL 失败重试 ---
    max_sql_retries: int = 1

    # --- 执行链路追踪 ---
    trace_enabled: bool = True
    trace_db_path: str = "../data/traces.db"

    # --- 上下文压缩 ---
    context_max_tokens: int = 4000
    context_keep_recent: int = 8

    # --- 取数超时与并行 ---
    query_timeout_seconds: float = 10.0
    query_retries: int = 1
    parallel_datasources: bool = True

    # --- 后台任务队列（跑在任务服务进程内）---
    task_workers: int = 2
    task_max_retries: int = 1
    task_timeout_seconds: float = 60.0

    # --- 任务服务（拆分出去的下游服务）---
    task_service_url: str = "http://127.0.0.1:8001"
    task_service_timeout_seconds: float = 3.0
    task_service_retries: int = 1

    # --- 定时调度 ---
    scheduler_enabled: bool = True
    scheduler_poll_seconds: float = 5.0
    scheduler_lock_ttl_seconds: float = 60.0

    # --- 数据接入 ---
    max_upload_mb: int = 20
    sample_seed_enabled: bool = True  # 启动时空库自动播种演示数据

    # --- 邮箱 ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # --- 日志 / 指标 ---
    log_level: str = "INFO"
    log_json: bool = True
    log_retention_days: int = 90
    metrics_enabled: bool = True

    # 同时支持从仓库根（../.env）和 backend/ 目录（.env）启动
    model_config = {"env_file": ("../.env", ".env"), "extra": "ignore"}

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        return origins or ["*"]

    @property
    def is_test(self) -> bool:
        return self.app_env.lower() in {"test", "ci"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """测试里切换环境变量后清缓存。"""
    get_settings.cache_clear()


if os.getenv("APP_ENV", "").lower() in {"prod", "production"}:  # pragma: no cover - 启动期提示
    import logging

    if Settings().auth_secret_key == "dev-only-change-me-in-production":
        logging.getLogger(__name__).warning(
            "AUTH_SECRET_KEY 仍是默认值，生产环境必须通过环境变量覆盖"
        )
