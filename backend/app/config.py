"""应用配置 — 通过 pydantic-settings 加载 .env"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- LLM ---
    llm_provider: str = "deepseek"  # deepseek | ollama | openai

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_temperature: float = 0.1  # 评测时建议设为 0，保证结果可复现

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # --- 数据库 ---
    database_url: str = "sqlite:///../data/agent.db"

    # --- 服务 ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- 沙箱 ---
    sandbox_timeout: int = 30

    # --- 查询限制 ---
    max_query_rows: int = 100_000
    max_return_rows: int = 10_000

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

    # --- 邮件 ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # --- 日志 ---
    log_level: str = "INFO"
    log_retention_days: int = 90

    # 同时支持从仓库根（../.env）和 backend/ 目录（.env）启动
    model_config = {"env_file": ("../.env", ".env"), "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
