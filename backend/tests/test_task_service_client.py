"""任务服务客户端测试：超时、5xx 重试、4xx 不重试、熔断、404。

用 httpx.MockTransport 模拟下游，不依赖真实端口。
"""

import httpx
import pytest

from app.services.task_service_client import (
    CircuitBreaker,
    DownstreamError,
    DownstreamRejected,
    TaskServiceClient,
    call_with_retry,
)


def _client(handler, *, retries=1, timeout=3.0) -> TaskServiceClient:
    return TaskServiceClient(
        "http://task-service.test",
        timeout=timeout,
        retries=retries,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_submit_returns_payload():
    def handler(request):
        assert request.url.path == "/tasks"
        return httpx.Response(200, json={"id": "t1", "status": "queued"})

    created = await _client(handler).submit("echo", {"n": 1})
    assert created == {"id": "t1", "status": "queued"}


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"id": "t2", "status": "queued"})

    created = await _client(handler, retries=1).submit("echo", {})
    assert created["id"] == "t2"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_5xx_exhausted_raises_downstream_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    with pytest.raises(DownstreamError):
        await _client(handler, retries=1).submit("echo", {})
    assert calls["n"] == 2  # 首次 + 重试一次


@pytest.mark.asyncio
async def test_4xx_is_not_retried_and_keeps_status():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"detail": "未注册的任务类型：nope"})

    with pytest.raises(DownstreamRejected) as exc:
        await _client(handler, retries=2).submit("nope", {})
    assert exc.value.status_code == 400
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_timeout_raises_downstream_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(DownstreamError) as exc:
        await _client(handler, retries=0).submit("echo", {})
    assert "不可达" in str(exc.value)


@pytest.mark.asyncio
async def test_get_returns_none_on_404():
    def handler(request):
        return httpx.Response(404, json={"detail": "任务不存在"})

    assert await _client(handler).get("missing") is None


@pytest.mark.asyncio
async def test_breaker_opens_after_threshold_and_fails_fast():
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=60)
    calls = {"n": 0}

    async def failing():
        calls["n"] += 1
        return httpx.Response(500, text="down")

    # 前两次：每次内部重试 0 次，失败记两次
    for _ in range(2):
        with pytest.raises(DownstreamError):
            await call_with_retry(failing, breaker=breaker, retries=0)

    assert breaker.state == "open"
    before = calls["n"]
    with pytest.raises(DownstreamError) as exc:
        await call_with_retry(failing, breaker=breaker, retries=0)
    assert "熔断" in str(exc.value)
    assert calls["n"] == before  # 熔断后没有再打下游


@pytest.mark.asyncio
async def test_breaker_resets_on_success():
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=60)

    async def ok():
        return httpx.Response(200, json={})

    async def bad():
        return httpx.Response(500, text="down")

    with pytest.raises(DownstreamError):
        await call_with_retry(bad, breaker=breaker, retries=0)
    await call_with_retry(ok, breaker=breaker, retries=0)
    assert breaker.state == "closed"
