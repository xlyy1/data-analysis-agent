"""步骤级超时与重试，用于取数链路。

取数可能碰到慢查询或数据源抖动：单次请求超时后重试一次往往能过，
但整体不能无限等——所以是"超时 + 有限重试"，不是无限重连。
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class StepTimeout(TimeoutError):
    """重试用尽仍未在超时时间内完成。"""


async def run_with_retry(
    factory: Callable[[], Awaitable[T]],
    *,
    timeout: float,
    retries: int = 1,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> tuple[T, int]:
    """执行 factory，超时则重试；返回 (结果, 实际尝试次数)。

    factory 每次调用都应建立自己的连接，避免复用失效连接。
    """
    attempts = 0
    last: BaseException | None = None

    while attempts <= retries:
        attempts += 1
        try:
            return await asyncio.wait_for(factory(), timeout=timeout), attempts
        except (asyncio.TimeoutError, TimeoutError) as exc:
            last = exc
            if attempts > retries:
                break
            if on_retry is not None:
                on_retry(attempts, exc)

    raise StepTimeout(f"step timed out after {attempts} attempt(s)") from last
