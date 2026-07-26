"""Ollama 本地模型适配器"""

from typing import AsyncIterator
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.llm.base import BaseLLM
from app.config import get_settings

_settings = get_settings()


class OllamaLLM(BaseLLM):
    def __init__(self):
        self._client = ChatOllama(
            model=_settings.ollama_model,
            base_url=_settings.ollama_base_url,
            temperature=0.1,
        )

    @property
    def model_name(self) -> str:
        return f"ollama/{_settings.ollama_model}"

    def _to_lc_messages(self, messages: list[dict]):
        role_map = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}
        return [role_map[m["role"]](content=m["content"]) for m in messages if m["role"] in role_map]

    async def chat(self, messages: list[dict], **kwargs) -> str:
        lc_msgs = self._to_lc_messages(messages)
        resp = await self._client.ainvoke(lc_msgs)
        return resp.content

    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        lc_msgs = self._to_lc_messages(messages)
        async for chunk in self._client.astream(lc_msgs):
            if chunk.content:
                yield chunk.content
