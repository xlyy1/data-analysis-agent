"""LLM 抽象基类"""

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
