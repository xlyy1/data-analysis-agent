"""审计查询 API 测试：权限、过滤、分页、敏感键遮蔽。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest

from app.database import async_session
from app.models.log import OperationLog
from app.models.user import User
from app.services.auth import hash_password

pytestmark = pytest.mark.asyncio


async def role_headers(client, role: str) -> dict:
    """建一个指定角色的真实用户并登录，返回 Bearer 头。"""
    username = f"audit_{role}_{uuid.uuid4().hex[:6]}"
    password = "probe12345"
    async with async_session() as session:
        session.add(
            User(
                username=username,
                display_name=role,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await session.commit()
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def add_log(action: str, user_id: str | None = "test-admin-id", detail: dict | None = None, when: datetime | None = None) -> str:
    async with async_session() as session:
        row = OperationLog(
            id=f"log-{uuid.uuid4().hex}",
            user_id=user_id,
            action=action,
            detail=json.dumps(detail or {}, ensure_ascii=False),
        )
        if when is not None:
            row.created_at = when
        session.add(row)
        await session.commit()
        return row.id


class TestPermissions:
    async def test_admin_can_read(self, client):
        response = await client.get("/api/audit")
        assert response.status_code == 200
        body = response.json()
        assert set(body) >= {"items", "total", "limit", "offset"}

    async def test_viewer_and_analyst_forbidden(self, anon_client):
        for role in ("viewer", "analyst"):
            headers = await role_headers(anon_client, role)
            response = await anon_client.get("/api/audit", headers=headers)
            assert response.status_code == 403, role
            assert response.json()["error"]["code"] == "forbidden"

    async def test_anonymous_unauthorized(self, anon_client):
        assert (await anon_client.get("/api/audit")).status_code == 401


class TestFilters:
    async def test_filter_by_action(self, client):
        await add_log("test_action_alpha")
        await add_log("test_action_beta")
        body = (await client.get("/api/audit", params={"action": "test_action_alpha"})).json()
        assert body["total"] >= 1
        assert all(item["action"] == "test_action_alpha" for item in body["items"])

    async def test_filter_by_user(self, client):
        await add_log("test_action_alpha", user_id="user-x")
        body = (await client.get("/api/audit", params={"user_id": "user-x"})).json()
        assert body["total"] >= 1
        assert all(item["user_id"] == "user-x" for item in body["items"])

    async def test_filter_by_since(self, client):
        old = datetime(2020, 1, 1, 0, 0, 0)
        await add_log("test_action_old", when=old)
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        body = (await client.get("/api/audit", params={"since": future})).json()
        assert all(item["action"] != "test_action_old" for item in body["items"])

    async def test_pagination_bounds(self, client):
        assert (await client.get("/api/audit", params={"limit": 0})).status_code == 422
        assert (await client.get("/api/audit", params={"limit": 201})).status_code == 422
        body = (await client.get("/api/audit", params={"limit": 1, "offset": 0})).json()
        assert len(body["items"]) <= 1

    async def test_actions_endpoint(self, client):
        await add_log("test_action_alpha")
        body = (await client.get("/api/audit/actions")).json()
        assert any(item["action"] == "test_action_alpha" and item["count"] >= 1 for item in body["items"])

    async def test_get_single_log(self, client):
        log_id = await add_log("test_action_single")
        response = await client.get(f"/api/audit/{log_id}")
        assert response.status_code == 200
        assert response.json()["id"] == log_id

    async def test_missing_log_is_404(self, client):
        response = await client.get("/api/audit/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "audit_not_found"


class TestSanitizing:
    async def test_sensitive_keys_are_masked(self, client):
        log_id = await add_log(
            "test_action_secret",
            detail={
                "datasource": "mysql-prod",
                "password": "super-secret-value",
                "nested": {"api_key": "sk-should-not-leak", "region": "cn"},
                "items": [{"token": "abc123"}],
            },
        )
        body = (await client.get(f"/api/audit/{log_id}")).json()
        serialized = json.dumps(body, ensure_ascii=False)
        assert "super-secret-value" not in serialized
        assert "sk-should-not-leak" not in serialized
        assert "abc123" not in serialized
        assert body["detail"]["password"] == "***"
        assert body["detail"]["nested"]["api_key"] == "***"
        # 非敏感字段保留，审计才有价值
        assert body["detail"]["datasource"] == "mysql-prod"
        assert body["detail"]["nested"]["region"] == "cn"

    async def test_malformed_detail_does_not_break_list(self, client):
        async with async_session() as session:
            session.add(
                OperationLog(id="log-broken", user_id="u", action="test_action_broken", detail="not-json{")
            )
            await session.commit()
        response = await client.get("/api/audit", params={"action": "test_action_broken"})
        assert response.status_code == 200
        assert response.json()["items"][0]["detail"]["_raw"].startswith("not-json")


class TestRealAuditTrail:
    async def test_login_is_audited(self, anon_client):
        """登录成功会写审计；这条链路端到端可查（用 admin 头读回）。"""
        admin = await role_headers(anon_client, "admin")
        viewer_username = f"audit_login_{uuid.uuid4().hex[:6]}"
        async with async_session() as session:
            session.add(
                User(
                    username=viewer_username,
                    display_name="probe",
                    password_hash=hash_password("probe12345"),
                    role="viewer",
                    is_active=True,
                )
            )
            await session.commit()

        assert (
            await anon_client.post(
                "/api/auth/login", json={"username": viewer_username, "password": "probe12345"}
            )
        ).status_code == 200

        body = (await anon_client.get("/api/audit", headers=admin, params={"action": "login"})).json()
        assert body["total"] >= 1
        assert any(item["action"] == "login" for item in body["items"])
