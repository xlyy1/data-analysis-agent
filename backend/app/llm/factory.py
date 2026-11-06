"""LLM 工厂函数 — 根据配置选择 provider"""

from app.llm.base import BaseLLM
from app.config import get_settings
from app.llm.deepseek import DeepSeekLLM
from app.llm.ollama import OllamaLLM


def get_llm(provider: str | None = None) -> BaseLLM:
    """返回配置的 LLM 实例"""
    settings = get_settings()
    provider = provider or settings.llm_provider

    if provider == "deepseek":
        return DeepSeekLLM()
    elif provider == "ollama":
        return OllamaLLM()
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        # 简单包装
        class OpenAILLM(BaseLLM):
            def __init__(self):
                self._client = ChatOpenAI(
                    model=settings.openai_model,
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    temperature=0.1,
                    streaming=True,
                )

            @property
            def model_name(self):
                return f"openai/{settings.openai_model}"

            async def chat(self, messages, **kwargs):
                from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

                role_map = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}
                lc_msgs = [role_map[m["role"]](content=m["content"]) for m in messages if m["role"] in role_map]
                resp = await self._client.ainvoke(lc_msgs)
                return resp.content

            async def chat_stream(self, messages, **kwargs):
                from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

                role_map = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}
                lc_msgs = [role_map[m["role"]](content=m["content"]) for m in messages if m["role"] in role_map]
                async for chunk in self._client.astream(lc_msgs):
                    if chunk.content:
                        yield chunk.content

        return OpenAILLM()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
