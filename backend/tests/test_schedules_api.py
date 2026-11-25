"""定时分析 API 测试：CRUD、立即执行、运行历史、删除带历史记录的计划。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.database import async_session
from app.models.schedule import ScheduleRun

pytestmark = pytest.mark.asyncio

SAMPLE = {"question": "各城市销售额", "interval_minutes": 60}


async def create_schedule(client, name: str = "每日经营日报"):
    response = await client.post("/api/schedules", json={"name": name, **SAMPLE})
    assert response.status_code == 201, response.text
    return response.json()


class TestCrud:
    async def test_create_and_list(self, client):
        created = await create_schedule(client)
        assert created["enabled"] is True
        assert created["next_run_at"], "创建后必须算出下次执行时间"
        listed = await client.get("/api/schedules")
        assert any(item["id"] == created["id"] for item in listed.json()["items"])

    async def test_interval_too_small_rejected(self, client):
        response = await client.post(
            "/api/schedules",
            json={"name": "too often", "question": "各城市销售额", "interval_minutes": 1},
        )
        assert response.status_code == 422

    async def test_patch_toggle_and_interval(self, client):
        created = await create_schedule(client)
        patched = await client.patch(
            f"/api/schedules/{created['id']}",
            json={"enabled": False, "interval_minutes": 180},
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["enabled"] is False
        assert body["interval_minutes"] == 180

    async def test_unknown_schedule_is_404(self, client):
        assert (await client.get("/api/schedules/nope")).status_code == 404

    async def test_delete_without_runs(self, client):
        created = await create_schedule(client)
        assert (await client.delete(f"/api/schedules/{created['id']}")).status_code == 200
        assert (await client.get(f"/api/schedules/{created['id']}")).status_code == 404

    async def test_delete_with_run_history(self, client):
        """回归：计划有运行记录时删除曾因外键约束返回 500。"""
        created = await create_schedule(client, name="有历史的计划")
        async with async_session() as session:
            session.add(
                ScheduleRun(
                    schedule_id=created["id"],
                    scheduled_for=datetime.utcnow(),
                    status="succeeded",
                )
            )
            await session.commit()

        response = await client.delete(f"/api/schedules/{created['id']}")
        assert response.status_code == 200, response.text

        async with async_session() as session:
            remaining = (
                await session.execute(
                    ScheduleRun.__table__.select().where(
                        ScheduleRun.schedule_id == created["id"]
                    )
                )
            ).all()
            assert remaining == [], "删除计划时其运行记录也应一并清理"

    async def test_ownership_isolation(self, client, role_patch):
        created = await create_schedule(client)
        role_patch("analyst")
        assert (await client.get(f"/api/schedules/{created['id']}")).status_code == 404


class TestRunNow:
    async def test_run_now_reports_downstream_unavailable(self, client):
        created = await create_schedule(client)
        # 测试环境 TASK_SERVICE_URL 指向不可达端口
        response = await client.post(f"/api/schedules/{created['id']}/run")
        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "task_service_unavailable"

        runs = await client.get(f"/api/schedules/{created['id']}/runs")
        assert runs.status_code == 200
        items = runs.json()["items"]
        assert items and items[0]["status"] == "failed", "提交失败也要留下可查的运行记录"
        assert "任务服务不可用" in (items[0]["error"] or "")

    async def test_run_now_success_path(self, client, monkeypatch):
        """注入一个能用的任务服务客户端，验证成功路径把 task_id 写回。"""
        from app.api import schedules as schedules_api

        class _FakeClient:
            async def submit(self, kind, payload):
                assert kind == "scheduled_analysis"
                assert payload["run_id"]
                return {"id": "task-fake-1", "status": "queued"}

        monkeypatch.setattr(schedules_api, "_client", lambda: _FakeClient())
        created = await create_schedule(client)
        response = await client.post(f"/api/schedules/{created['id']}/run")
        assert response.status_code == 200, response.text
        assert response.json()["task_id"] == "task-fake-1"

        runs = (await client.get(f"/api/schedules/{created['id']}/runs")).json()["items"]
        assert runs[0]["task_id"] == "task-fake-1"
