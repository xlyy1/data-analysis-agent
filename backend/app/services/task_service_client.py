"""服务间调用的最小客户端：超时、有限重试、熔断。

调用下游（任务服务）时不能无限等：超时要短，重试要有上限，连续失败就熔断一段时间，
把请求快速失败掉，避免 API 被下游拖死。
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

import httpx


class DownstreamError(RuntimeError):
    """下游服务不可用（超时 / 连接失败 / 5xx 重试后仍失败）。"""


class DownstreamRejected(DownstreamError):
    """下游明确拒绝（4xx）：请求本身有问题，不该重试，也不该算熔断失败。"""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class CircuitBreaker:
    """连续失败 N 次后打开，冷却期内的请求直接拒绝。"""

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 15.0) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if time.monotonic() - self._opened_at >= self._cooldown:
            # 冷却结束，进入半开：放一个请求试试
            return "half_open"
        return "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = time.monotonic()

    def allow(self) -> bool:
        return self.state != "open"


async def call_with_retry(
    call: Callable[[], Awaitable[httpx.Response]],
    *,
    breaker: CircuitBreaker | None = None,
    retries: int = 1,
) -> httpx.Response:
    """执行一次 HTTP 调用；超时与 5xx 会重试，重试用尽抛 DownstreamError。"""
    if breaker is not None and not breaker.allow():
        raise DownstreamError("下游熔断中，快速失败")

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = await call()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            if breaker is not None:
                breaker.record_failure()
            if attempt < retries:
                continue
            raise DownstreamError(f"下游不可达：{exc}") from exc

        if response.status_code >= 500:
            last = DownstreamError(f"下游返回 {response.status_code}")
            if breaker is not None:
                breaker.record_failure()
            if attempt < retries:
                continue
            raise last

        if breaker is not None:
            breaker.record_success()
        return response

    raise DownstreamError(str(last) if last else "下游调用失败")


class TaskServiceClient:
    """任务服务的客户端：API 侧只依赖这个接口，不关心下游实现。

    transport 可注入（测试里用 ASGITransport 直连任务服务，不必起端口）。
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 3.0,
        retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = retries
        self._transport = transport
        self._breaker = CircuitBreaker()

    @property
    def breaker_state(self) -> str:
        return self._breaker.state

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path}"

        async def call() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                return await client.request(method, url, **kwargs)

        return await call_with_retry(call, breaker=self._breaker, retries=self._retries)

    async def submit(self, kind: str, payload: dict) -> dict:
        response = await self._request("POST", "/tasks", json={"kind": kind, "payload": payload})
        if 400 <= response.status_code < 500:
            # 下游拒绝（比如任务类型没注册）：原样上抛，交给 API 映射成 4xx
            raise DownstreamRejected(response.text[:200], response.status_code)
        if response.status_code >= 500:
            raise DownstreamError(response.text[:200])
        return response.json()

    async def get(self, task_id: str) -> dict | None:
        response = await self._request("GET", f"/tasks/{task_id}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise DownstreamError(response.text[:200])
        return response.json()

    async def list(self, status: str | None = None, limit: int = 20) -> list[dict]:
        params = {"limit": limit}
        if status:
            params["status"] = status
        response = await self._request("GET", "/tasks", params=params)
        if response.status_code >= 400:
            raise DownstreamError(response.text[:200])
        return response.json().get("items", [])

    async def healthz(self) -> bool:
        try:
            response = await self._request("GET", "/healthz")
        except DownstreamError:
            return False
        return response.status_code == 200
