"""LLM 工厂函数 — 根据配置选择 provider"""

from app.llm.base import BaseLLM, TimedLLM
from app.config import get_settings
from app.llm.deepseek import DeepSeekLLM
from app.llm.mock import MockLLM
from app.llm.ollama import OllamaLLM


def get_llm(provider: str | None = None) -> BaseLLM:
    """返回配置的 LLM 实例。

    统一套一层 `TimedLLM`：任何 provider 都必须有硬超时，避免"模型不可达"变成
    "接口永远不返回"。mock 是纯本地计算，不需要包装。
    """
    settings = get_settings()
    provider = provider or settings.llm_provider

    if provider == "mock":
        # 离线/CI 用：确定性输出，不访问网络
        return MockLLM()

    impl = _create_provider(provider, settings)
    return TimedLLM(impl, settings.llm_request_timeout_seconds)


def _create_provider(provider: str, settings) -> BaseLLM:
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
                    timeout=settings.llm_request_timeout_seconds,
                    max_retries=settings.llm_max_retries,
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
