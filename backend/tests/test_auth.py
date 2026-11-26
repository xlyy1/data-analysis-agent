"""认证与权限测试：登录 / 刷新轮换 / 越权 / 用户管理 / 密码哈希。

这些用例走**真实 JWT 校验**（`anon_client` / `admin_headers` 不覆盖鉴权依赖），
用户直接写库创建，避免"先用管理员建管理员"的循环依赖。
"""

from __future__ import annotations

import uuid


from app.database import async_session
from app.models.user import User
from app.services.auth import hash_password, permissions_for, verify_password


def unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def create_user_db(role: str = "viewer", password: str = "passw0rd123") -> tuple[str, str]:
    username = unique(role)
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
    return username, password


async def login(client, username: str, password: str):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def bearer(client, role: str = "viewer") -> dict:
    username, password = await create_user_db(role)
    response = await login(client, username, password)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestPasswordHashing:
    def test_hash_is_not_reversible_and_verifies(self):
        stored = hash_password("s3cret-pass")
        assert "s3cret-pass" not in stored
        assert stored.startswith("pbkdf2_sha256$")
        assert verify_password("s3cret-pass", stored) is True
        assert verify_password("wrong", stored) is False

    def test_same_password_different_salt(self):
        assert hash_password("abc") != hash_password("abc")

    def test_malformed_hash_returns_false(self):
        assert verify_password("x", "not-a-hash") is False


class TestRoleMatrix:
    def test_admin_has_everything_sensitive(self):
        perms = permissions_for("admin")
        assert {"datasource:write", "user:manage", "sql:write"} <= perms

    def test_viewer_cannot_write_datasource_or_sql(self):
        perms = permissions_for("viewer")
        assert "datasource:write" not in perms
        assert "sql:write" not in perms
        assert "user:manage" not in perms
        assert "datasource:read" in perms

    def test_analyst_between_admin_and_viewer(self):
        perms = permissions_for("analyst")
        assert "datasource:write" in perms
        assert "user:manage" not in perms
        assert "sql:write" not in perms

    def test_unknown_role_has_no_permissions(self):
        assert permissions_for("root") == set()


class TestLogin:
    async def test_no_token_is_401(self, anon_client):
        response = await anon_client.get("/api/datasources")
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == "unauthorized"
        assert body["error"]["request_id"]

    async def test_bad_token_is_401(self, anon_client):
        response = await anon_client.get(
            "/api/datasources", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    async def test_login_and_me(self, anon_client):
        username, password = await create_user_db("viewer")
        response = await login(anon_client, username, password)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert body["user"]["role"] == "viewer"
        assert "datasource:read" in body["user"]["permissions"]

        me = await anon_client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert me.status_code == 200
        assert me.json()["username"] == username

    async def test_wrong_password_and_missing_user_share_message(self, anon_client):
        username, _ = await create_user_db("viewer")
        wrong = await login(anon_client, username, "wrong-one")
        assert wrong.status_code == 401
        missing = await login(anon_client, "no-such-user-xyz", "wrong-one")
        assert missing.status_code == 401
        # 不区分"用户不存在"和"密码错误"，避免账号枚举
        assert wrong.json()["error"]["message"] == missing.json()["error"]["message"]

    async def test_disabled_user_cannot_login(self, anon_client, admin_headers):
        username, password = await create_user_db("viewer")
        users = (await anon_client.get("/api/auth/users", headers=admin_headers)).json()["items"]
        target = next(item for item in users if item["username"] == username)
        patched = await anon_client.patch(
            f"/api/auth/users/{target['id']}", headers=admin_headers, json={"is_active": False}
        )
        assert patched.status_code == 200
        response = await login(anon_client, username, password)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "user_disabled"


class TestRefreshRotation:
    async def test_refresh_rotates_and_revokes_old(self, anon_client):
        username, password = await create_user_db("analyst")
        tokens = (await login(anon_client, username, password)).json()

        first = await anon_client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert first.status_code == 200
        new_tokens = first.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

        replay = await anon_client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert replay.status_code == 401

        usable = await anon_client.get(
            "/api/datasources",
            headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
        )
        assert usable.status_code == 200

    async def test_refresh_token_cannot_be_used_as_access(self, anon_client):
        username, password = await create_user_db("viewer")
        tokens = (await login(anon_client, username, password)).json()
        response = await anon_client.get(
            "/api/datasources", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
        )
        assert response.status_code == 401

    async def test_logout_revokes_refresh(self, anon_client):
        username, password = await create_user_db("viewer")
        tokens = (await login(anon_client, username, password)).json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        assert (
            await anon_client.post(
                "/api/auth/logout",
                json={"refresh_token": tokens["refresh_token"]},
                headers=headers,
            )
        ).status_code == 200
        replay = await anon_client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert replay.status_code == 401


class TestUserManagement:
    async def test_create_and_list(self, anon_client, admin_headers):
        username = unique("created")
        created = await anon_client.post(
            "/api/auth/users",
            headers=admin_headers,
            json={"username": username, "password": "passw0rd123", "role": "analyst"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["role"] == "analyst"

        users = (await anon_client.get("/api/auth/users", headers=admin_headers)).json()["items"]
        assert any(item["username"] == username for item in users)

    async def test_duplicate_username_conflicts(self, anon_client, admin_headers):
        username, _ = await create_user_db("viewer")
        again = await anon_client.post(
            "/api/auth/users",
            headers=admin_headers,
            json={"username": username, "password": "passw0rd123", "role": "viewer"},
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "username_taken"

    async def test_invalid_role_rejected(self, anon_client, admin_headers):
        response = await anon_client.post(
            "/api/auth/users",
            headers=admin_headers,
            json={"username": unique("bad"), "password": "passw0rd123", "role": "superuser"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_role"

    async def test_cannot_demote_or_disable_self(self, anon_client, admin_headers):
        me = (await anon_client.get("/api/auth/me", headers=admin_headers)).json()
        demote = await anon_client.patch(
            f"/api/auth/users/{me['id']}", headers=admin_headers, json={"role": "viewer"}
        )
        assert demote.status_code == 400
        assert demote.json()["error"]["code"] == "cannot_change_own_role"
        disable = await anon_client.patch(
            f"/api/auth/users/{me['id']}", headers=admin_headers, json={"is_active": False}
        )
        assert disable.status_code == 400
        assert disable.json()["error"]["code"] == "cannot_disable_self"

    async def test_password_change_takes_effect(self, anon_client, admin_headers):
        username, _ = await create_user_db("viewer")
        users = (await anon_client.get("/api/auth/users", headers=admin_headers)).json()["items"]
        target = next(item for item in users if item["username"] == username)
        patched = await anon_client.patch(
            f"/api/auth/users/{target['id']}",
            headers=admin_headers,
            json={"password": "newpass12345"},
        )
        assert patched.status_code == 200
        assert (await login(anon_client, username, "passw0rd123")).status_code == 401
        assert (await login(anon_client, username, "newpass12345")).status_code == 200

    async def test_delete_is_soft_and_blocks_login(self, anon_client, admin_headers):
        username, password = await create_user_db("viewer")
        users = (await anon_client.get("/api/auth/users", headers=admin_headers)).json()["items"]
        target = next(item for item in users if item["username"] == username)
        assert (
            await anon_client.delete(
                f"/api/auth/users/{target['id']}", headers=admin_headers
            )
        ).status_code == 200
        assert (await login(anon_client, username, password)).status_code == 403

    async def test_permission_matrix_endpoint(self, anon_client, admin_headers):
        body = (await anon_client.get("/api/auth/permissions", headers=admin_headers)).json()
        assert "viewer" in body["roles"]
        assert body["current"]["role"] == "admin"
        assert body["sql_write_allowed"] is True


class TestViewerIsReadOnly:
    async def test_viewer_cannot_write_resources(self, anon_client):
        viewer = await bearer(anon_client, "viewer")

        create_ds = await anon_client.post(
            "/api/datasources",
            headers=viewer,
            json={"name": "x", "type": "sqlite", "config": {"db_path": "/tmp/x.db"}},
        )
        assert create_ds.status_code == 403
        assert create_ds.json()["error"]["code"] == "forbidden"

        create_schedule = await anon_client.post(
            "/api/schedules",
            headers=viewer,
            json={"name": "n", "question": "各城市销售额", "interval_minutes": 60},
        )
        assert create_schedule.status_code == 403

        validate_sql = await anon_client.post(
            "/api/sql/validate", headers=viewer, json={"sql": "SELECT 1"}
        )
        assert validate_sql.status_code == 403

    async def test_viewer_can_read_and_chat(self, anon_client):
        viewer = await bearer(anon_client, "viewer")
        assert (await anon_client.get("/api/datasources", headers=viewer)).status_code == 200
        assert (await anon_client.get("/api/conversations/", headers=viewer)).status_code == 200
        assert (await anon_client.get("/api/auth/me", headers=viewer)).status_code == 200
