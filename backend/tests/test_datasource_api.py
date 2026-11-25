"""数据源 API 测试：CRUD、连接测试、上传清洗、大小/类型/路径穿越防护、增量重导。"""

from __future__ import annotations


import pytest

from app.api import datasource as datasource_api
from app.core.sqlite import sqlite_connection

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """把上传/落库目录指到临时目录，测试不污染仓库 data/。"""
    uploads = tmp_path / "uploads"
    ingested = tmp_path / "ingested"
    uploads.mkdir()
    ingested.mkdir()
    monkeypatch.setattr(datasource_api, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(datasource_api, "INGEST_DIR", ingested)
    return {"uploads": uploads, "ingested": ingested, "tmp": tmp_path}


def make_sqlite(tmp_path, name: str = "biz.db"):
    path = tmp_path / name
    with sqlite_connection(path) as conn:
        conn.execute('CREATE TABLE orders (city TEXT, amount REAL, note TEXT)')
        conn.executemany(
            "INSERT INTO orders VALUES (?,?,?)",
            [("杭州", 100.0, None), ("苏州", 200.0, "vip"), ("杭州", 300.0, None)],
        )
        conn.commit()
    return path


class TestCrud:
    async def test_create_list_get_patch_delete(self, client, tmp_path):
        db_path = make_sqlite(tmp_path)
        created = await client.post(
            "/api/datasources",
            json={"name": "业务库", "type": "sqlite", "config": {"db_path": str(db_path)}},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        ds_id = body["id"]
        assert body["table_count"] == 1
        assert body["schema"]["tables"][0]["name"] == "orders"
        assert body["profile"]["tables"][0]["row_count"] == 3

        listed = await client.get("/api/datasources")
        assert any(item["id"] == ds_id for item in listed.json()["items"])

        detail = await client.get(f"/api/datasources/{ds_id}")
        assert detail.status_code == 200
        assert detail.json()["name"] == "业务库"

        patched = await client.patch(f"/api/datasources/{ds_id}", json={"name": "业务库-改名"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "业务库-改名"

        deleted = await client.delete(f"/api/datasources/{ds_id}")
        assert deleted.status_code == 200
        after = await client.get("/api/datasources")
        assert all(item["id"] != ds_id for item in after.json()["items"])

    async def test_missing_required_field(self, client):
        response = await client.post(
            "/api/datasources", json={"name": "x", "type": "sqlite", "config": {}}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_config"

    async def test_unsupported_type(self, client):
        response = await client.post(
            "/api/datasources", json={"name": "x", "type": "mongodb", "config": {"host": "h"}}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "unsupported_type"

    async def test_nonexistent_sqlite_file(self, client, tmp_path):
        response = await client.post(
            "/api/datasources",
            json={"name": "x", "type": "sqlite", "config": {"db_path": str(tmp_path / "nope.db")}},
        )
        assert response.status_code == 400
        assert "不存在" in response.json()["error"]["message"]

    async def test_password_is_redacted(self, client):
        response = await client.post(
            "/api/datasources",
            json={
                "name": "mysql-probe",
                "type": "mysql",
                "config": {
                    "host": "127.0.0.1",
                    "port": 3306,
                    "user": "u",
                    "password": "super-secret",
                    "database": "db",
                },
            },
        )
        # 连不上是预期的（没有 MySQL），但配置不能泄露密码
        assert response.status_code == 400
        assert "super-secret" not in response.text

    async def test_supported_types_endpoint(self, client):
        body = (await client.get("/api/datasources/supported-types")).json()
        assert {item["type"] for item in body["types"]} >= {"sqlite", "mysql", "postgres", "excel", "csv"}
        assert body["max_upload_mb"] > 0


class TestConnectionTest:
    async def test_ok(self, client, tmp_path):
        db_path = make_sqlite(tmp_path)
        response = await client.post(
            "/api/datasources/test",
            json={"name": "t", "type": "sqlite", "config": {"db_path": str(db_path)}},
        )
        body = response.json()
        assert body["ok"] is True
        assert body["tables"][0]["name"] == "orders"
        assert body["latency_ms"] >= 0

    async def test_failure_is_reported_not_raised(self, client, tmp_path):
        response = await client.post(
            "/api/datasources/test",
            json={"name": "t", "type": "sqlite", "config": {"db_path": str(tmp_path / "x.db")}},
        )
        assert response.status_code == 400


class TestUpload:
    async def test_csv_upload_reports_cleaning(self, client, sandbox):
        content = (
            " 门店编号 ,城市,销售额\n"
            "0012, 杭州 ,100\n"
            "0012, 杭州 ,100\n"
            ",,\n"
        ).encode("utf-8")
        response = await client.post(
            "/api/datasources/upload",
            files={"file": ("门店经营.csv", content, "text/csv")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["ingest"]["dropped_blank"] == 1
        assert body["ingest"]["dropped_duplicate"] == 1
        assert body["table_count"] == 1

        # 落盘文件名不能沿用用户输入，必须是 uuid
        stored = list(sandbox["uploads"].iterdir())
        assert len(stored) == 1
        assert stored[0].name != "门店经营.csv"
        assert stored[0].name.endswith(".csv")

    async def test_path_traversal_filename_is_neutralized(self, client, sandbox):
        content = "城市,销售额\n杭州,1\n".encode("utf-8")
        response = await client.post(
            "/api/datasources/upload",
            files={"file": ("../../evil.csv", content, "text/csv")},
        )
        assert response.status_code == 201
        body = response.json()
        assert "/" not in body["config"]["file_name"]
        # 只在 uploads 目录里生成 uuid 文件，仓库根目录不会多出 evil.csv
        assert [p.name for p in sandbox["uploads"].iterdir()] != ["evil.csv"]
        assert not (sandbox["tmp"].parent / "evil.csv").exists()

    async def test_bad_extension_rejected(self, client, sandbox):
        response = await client.post(
            "/api/datasources/upload",
            files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_upload"

    async def test_oversize_rejected(self, client, sandbox):
        # conftest 把上限设成 5MB
        big = b"a,b\n" + b"1,2\n" * 1_500_000
        response = await client.post(
            "/api/datasources/upload", files={"file": ("big.csv", big, "text/csv")}
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "upload_too_large"

    async def test_empty_file_rejected(self, client, sandbox):
        response = await client.post(
            "/api/datasources/upload", files={"file": ("empty.csv", b"", "text/csv")}
        )
        assert response.status_code == 400

    async def test_reingest_append_is_idempotent(self, client, sandbox):
        content = "城市,销售额\n杭州,1\n苏州,2\n".encode("utf-8")
        created = await client.post(
            "/api/datasources/upload", files={"file": ("sales.csv", content, "text/csv")}
        )
        ds_id = created.json()["id"]
        assert created.json()["row_count"] == 2

        first = await client.post(f"/api/datasources/{ds_id}/reingest", params={"append": "true"})
        assert first.status_code == 200
        assert first.json()["ingest"]["rows_written"] == 0, "同一份文件重复增量导入不应新增行"

        second = await client.post(f"/api/datasources/{ds_id}/reingest", params={"append": "true"})
        assert second.json()["ingest"]["rows_written"] == 0
        assert second.json()["datasource"]["row_count"] == 2

    async def test_reingest_requires_source_file(self, client, tmp_path):
        db_path = make_sqlite(tmp_path)
        created = await client.post(
            "/api/datasources",
            json={"name": "库", "type": "sqlite", "config": {"db_path": str(db_path)}},
        )
        ds_id = created.json()["id"]
        response = await client.post(f"/api/datasources/{ds_id}/reingest")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "no_source_file"


class TestProfileAndSchema:
    async def test_profile_and_refresh(self, client, tmp_path):
        db_path = make_sqlite(tmp_path)
        created = await client.post(
            "/api/datasources",
            json={"name": "库", "type": "sqlite", "config": {"db_path": str(db_path)}},
        )
        ds_id = created.json()["id"]

        profile = await client.get(f"/api/datasources/{ds_id}/profile")
        assert profile.status_code == 200
        assert profile.json()["tables"][0]["row_count"] == 3

        refreshed = await client.post(f"/api/datasources/{ds_id}/refresh-schema")
        assert refreshed.status_code == 200
        assert refreshed.json()["schema"]["tables"]

        tested = await client.post(f"/api/datasources/{ds_id}/test")
        assert tested.json()["ok"] is True
