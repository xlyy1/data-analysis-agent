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

    # --- 邮件 ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # --- 日志 ---
    log_level: str = "INFO"
    log_retention_days: int = 90

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
