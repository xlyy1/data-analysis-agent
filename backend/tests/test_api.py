"""API 集成测试"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestConversationEndpoints:
    @pytest.mark.asyncio
    async def test_create_conversation(self, client: AsyncClient):
        resp = await client.post("/api/conversations/")
        assert resp.status_code == 200
        conv_id = resp.json()["id"]
        assert conv_id

    @pytest.mark.asyncio
    async def test_list_conversations(self, client: AsyncClient):
        resp = await client.get("/api/conversations/")
        assert resp.status_code == 200
