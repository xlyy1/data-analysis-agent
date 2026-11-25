"""系统探针 / 指标 / 统一错误体 / request_id 测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestProbes:
    async def test_healthz_is_public(self, anon_client):
        response = await anon_client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["uptime_seconds"] >= 0

    async def test_readyz_reports_checks(self, anon_client):
        response = await anon_client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checks"]["database"]["ok"] is True
        assert "task_service" in body["checks"]

    async def test_metrics_is_prometheus_text(self, anon_client):
        await anon_client.get("/healthz")
        response = await anon_client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        text = response.text
        assert "# TYPE dsh_http_requests_total counter" in text
        assert 'path="/healthz"' in text
        assert "dsh_sql_guarded_total" in text

    async def test_legacy_health_endpoint_still_works(self, anon_client):
        response = await anon_client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_index_lists_entry_points(self, anon_client):
        body = (await anon_client.get("/")).json()
        assert body["docs"] == "/docs"
        assert body["health"] == "/healthz"


class TestRequestId:
    async def test_response_carries_request_id(self, anon_client):
        response = await anon_client.get("/healthz")
        assert response.headers.get("X-Request-ID")

    async def test_incoming_request_id_is_echoed(self, anon_client):
        response = await anon_client.get("/healthz", headers={"X-Request-ID": "abc-123"})
        assert response.headers["X-Request-ID"] == "abc-123"

    async def test_unsafe_request_id_is_sanitized(self, anon_client):
        response = await anon_client.get(
            "/healthz", headers={"X-Request-ID": "a b\nc;drop table x"}
        )
        value = response.headers["X-Request-ID"]
        assert "\n" not in value
        assert ";" not in value
        assert len(value) <= 64


class TestUnifiedErrors:
    async def test_not_found_body_shape(self, client):
        response = await client.get("/api/datasources/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "datasource_not_found"
        assert body["error"]["message"]
        assert body["error"]["request_id"]
        # 兼容字段
        assert body["detail"] == body["error"]["message"]

    async def test_validation_error_shape(self, client, anon_client):
        response = await anon_client.post("/api/auth/login", json={"username": ""})
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["details"]["errors"]

    async def test_unauthenticated_uses_unified_body(self, anon_client):
        response = await anon_client.get("/api/conversations/")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
