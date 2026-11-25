"""LLM 抽象基类。

除统一接口外，这里还提供一个 `TimedLLM` 包装器：给任何 provider 套一层硬超时。
为什么需要：底层 SDK 的 `timeout` / `max_retries` 组合起来可能把一次调用拖到几分钟，
而一次分析要调 4~5 次模型。没有这层兜底时，"模型不可达"会变成"接口一直不返回"，
用户看到的是白屏，日志里也看不出卡在哪。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseLLM(ABC):
    """LLM 统一接口"""

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> str:
        """发送消息列表，返回完整回复"""
        ...

    @abstractmethod
    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """流式对话"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


class LLMTimeoutError(TimeoutError):
    """模型调用超时（对外统一成一个可识别的异常类型）。"""


class TimedLLM(BaseLLM):
    """给任意 provider 套一层 asyncio 硬超时。"""

    def __init__(self, inner: BaseLLM, timeout_seconds: float) -> None:
        self._inner = inner
        self._timeout = max(1.0, float(timeout_seconds))

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def chat(self, messages: list[dict], **kwargs) -> str:
        try:
            return await asyncio.wait_for(
                self._inner.chat(messages, **kwargs), timeout=self._timeout
            )
        except asyncio.TimeoutError as error:
            raise LLMTimeoutError(
                f"模型调用超过 {self._timeout:.0f}s 未返回（{self.model_name}）"
            ) from error

    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        async for chunk in self._inner.chat_stream(messages, **kwargs):
            yield chunk
