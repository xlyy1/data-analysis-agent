"""报告 API 测试：落库、格式下载、越权隔离、404。"""

from __future__ import annotations


import pytest

from app.database import async_session
from app.services.conversation import ConversationService

pytestmark = pytest.mark.asyncio


async def seed_conversation(user_id: str = "test-admin-id") -> str:
    async with async_session() as session:
        service = ConversationService(session)
        conversation = await service.create_conversation(user_id, title="各城市销售额")
        await service.add_message(conversation.id, "user", "各城市的销售额排名")
        await service.add_message(
            conversation.id,
            "assistant",
            "杭州最高，为 1800 元。",
            {
                "sql": 'SELECT "城市", SUM("销售额") FROM "订单明细" GROUP BY 1',
                "chart_config": {"chart_type": "bar"},
                "diagnosis_causes": ["批发渠道毛利偏低"],
                "diagnosis_suggestions": ["收紧批发折扣"],
                "data_columns": ["城市", "销售额"],
                "data_rows": [["杭州", 1800], ["苏州", 1200]],
            },
        )
        return conversation.id


class TestGenerate:
    async def test_generate_json_persists_report(self, client):
        conversation_id = await seed_conversation()
        response = await client.post(
            "/api/reports/generate", json={"conversation_id": conversation_id, "format": "json"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"]
        assert body["markdown_preview"].startswith("# 数据分析报告")
        assert set(body["download"]) == {"markdown", "html", "pdf"}

        listed = await client.get("/api/reports")
        assert listed.status_code == 200
        assert any(item["id"] == body["id"] for item in listed.json()["items"])

    async def test_unknown_conversation_is_404(self, client):
        response = await client.post(
            "/api/reports/generate", json={"conversation_id": "nope", "format": "json"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"

    async def test_unsupported_format_rejected(self, client):
        conversation_id = await seed_conversation()
        response = await client.post(
            "/api/reports/generate", json={"conversation_id": conversation_id, "format": "xlsx"}
        )
        assert response.status_code == 422


class TestDownload:
    @pytest.mark.parametrize("fmt", ["markdown", "html", "pdf"])
    async def test_download_formats(self, client, fmt):
        conversation_id = await seed_conversation()
        created = await client.post(
            "/api/reports/generate", json={"conversation_id": conversation_id, "format": "json"}
        )
        report_id = created.json()["id"]
        response = await client.get(f"/api/reports/{report_id}/download", params={"format": fmt})
        assert response.status_code == 200
        assert len(response.content) > 50
        if fmt == "pdf":
            assert response.content.startswith(b"%PDF")
        if fmt == "markdown":
            assert "数据分析报告" in response.content.decode("utf-8")

    async def test_get_report_markdown_body(self, client):
        conversation_id = await seed_conversation()
        created = await client.post(
            "/api/reports/generate", json={"conversation_id": conversation_id, "format": "json"}
        )
        report_id = created.json()["id"]
        detail = await client.get(f"/api/reports/{report_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert "## 原始问题" in body["markdown"]
        assert "杭州最高" in body["markdown"]

    async def test_other_users_report_is_hidden(self, client, role_patch):
        conversation_id = await seed_conversation()
        created = await client.post(
            "/api/reports/generate", json={"conversation_id": conversation_id, "format": "json"}
        )
        report_id = created.json()["id"]

        role_patch("analyst")
        response = await client.get(f"/api/reports/{report_id}")
        assert response.status_code == 404, "别人的报告应当表现为不存在"

    async def test_delete_report(self, client):
        conversation_id = await seed_conversation()
        created = await client.post(
            "/api/reports/generate", json={"conversation_id": conversation_id, "format": "json"}
        )
        report_id = created.json()["id"]
        assert (await client.delete(f"/api/reports/{report_id}")).status_code == 200
        assert (await client.get(f"/api/reports/{report_id}")).status_code == 404
