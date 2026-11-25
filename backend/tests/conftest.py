"""测试全局配置。

关键约束：**不依赖任何付费 Key / 外网**。
- 数据库指向本会话独占的临时文件，测试之间不再往 data/agent.db 里写脏数据；
- LLM 固定为 `mock`（确定性输出），不会真的请求 DeepSeek；
- 任务服务地址指向不可达端口，需要它的用例自己 monkeypatch；
- 默认把鉴权依赖覆盖成"测试管理员"，这样已有用例不用改动就能继续验证业务逻辑；
  鉴权/权限本身的用例显式使用不带覆盖的 client（见 tests/test_auth.py）。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="data-agent-tests-"))
_TRACE_DB = _TMP_DIR / "traces.db"

os.environ.update(
    {
        "APP_ENV": "test",
        "DEBUG": "false",
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP_DIR / 'test.db').as_posix()}",
        "AUTH_SECRET_KEY": "test-secret-key-do-not-use-in-production",
        "ACCESS_TOKEN_MINUTES": "30",
        "REFRESH_TOKEN_DAYS": "1",
        "BOOTSTRAP_ADMIN_USERNAME": "admin",
        "BOOTSTRAP_ADMIN_PASSWORD": "admin12345",
        # 测试里登录次数远超真实用户，放宽限流避免误报 429（限流本身另有用例覆盖）
        "LOGIN_RATE_LIMIT_PER_MINUTE": "10000",
        "LLM_PROVIDER": "mock",
        "DEEPSEEK_API_KEY": "",
        "OPENAI_API_KEY": "",
        "TRACE_DB_PATH": _TRACE_DB.as_posix(),
        "SAMPLE_SEED_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "TASK_SERVICE_URL": "http://127.0.0.1:9",
        "TASK_SERVICE_TIMEOUT_SECONDS": "0.5",
        "TASK_SERVICE_RETRIES": "0",
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
        "MAX_UPLOAD_MB": "5",
    }
)

from app.database import engine, init_db  # noqa: E402
from app.models.user import ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER, User  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """整轮测试只建一次表（表结构由 app.models 的 metadata 决定）。"""

    async def _create() -> None:
        await init_db()

    asyncio.run(_create())
    yield
    asyncio.run(engine.dispose())


@pytest.fixture(scope="session")
def app_module():
    from app.main import app

    return app


@pytest.fixture(scope="session", autouse=True)
def _seed_admin(_schema):
    """在测试库里建一个真实管理员，供"走真实 JWT 校验"的用例登录。

    直接写库而不是调接口，避免"要先用管理员建管理员"的循环依赖。
    """
    from sqlalchemy import select

    from app.database import async_session
    from app.models.user import ROLE_ADMIN, User
    from app.services.auth import hash_password

    async def _run() -> None:
        async with async_session() as session:
            existing = (
                await session.execute(select(User).where(User.username == "admin"))
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    User(
                        username="admin",
                        display_name="系统管理员",
                        password_hash=hash_password("admin12345"),
                        role=ROLE_ADMIN,
                        is_active=True,
                    )
                )
                await session.commit()

    asyncio.run(_run())


@pytest.fixture(scope="session")
def admin_user() -> User:
    return User(
        id="test-admin-id",
        username="admin",
        display_name="测试管理员",
        role=ROLE_ADMIN,
        is_active=True,
        password_hash="x",
    )


@pytest.fixture(autouse=True)
def override_auth(request):
    """默认放行：把 get_current_user 覆盖成测试管理员。

    需要验证"未登录/越权"的用例打 `@pytest.mark.no_auth_override` 跳过覆盖。
    """
    if request.node.get_closest_marker("no_auth_override"):
        yield
        return

    from app.api import deps
    from app.main import app

    fake = User(
        id="test-admin-id",
        username="admin",
        display_name="测试管理员",
        role=ROLE_ADMIN,
        is_active=True,
        password_hash="x",
    )
    previous = app.dependency_overrides.get(deps.get_current_user)
    app.dependency_overrides[deps.get_current_user] = lambda: fake

    from httpx import ASGITransport, AsyncClient

    # 把 client 工厂挂在 request 上，供需要它的用例直接取用
    request.client_factory = lambda: AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    )
    yield fake
    if previous is None:
        app.dependency_overrides.pop(deps.get_current_user, None)
    else:
        app.dependency_overrides[deps.get_current_user] = previous


@pytest.fixture
async def client(override_auth):
    """已鉴权（admin）的异步 client（依赖覆盖，不校验 JWT）。"""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _cleared_app():
    """临时摘掉所有 dependency_overrides 的应用实例上下文。"""
    from contextlib import asynccontextmanager
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    @asynccontextmanager
    async def _ctx():
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                yield ac
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    return _ctx()


@pytest.fixture
async def anon_client():
    """不带鉴权覆盖的 client —— 走真实 JWT 校验，用于验证 401/403。"""
    async with _cleared_app() as ac:
        yield ac


@pytest.fixture
async def admin_headers():
    """真实登录拿到的 admin Bearer 头。"""
    async with _cleared_app() as ac:
        response = await ac.post(
            "/api/auth/login", json={"username": "admin", "password": "admin12345"}
        )
        assert response.status_code == 200, response.text
        yield {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def role_patch(app_module):
    """把当前用户切换成指定角色（用于验证 viewer 只读）。"""

    def _patch(role: str):
        from app.api import deps

        fake = User(
            id=f"test-{role}-id",
            username=f"test-{role}",
            display_name=role,
            role=role,
            is_active=True,
            password_hash="x",
        )
        app_module.dependency_overrides[deps.get_current_user] = lambda: fake
        return fake

    return _patch


@pytest.fixture
def anyio_backend():
    return "asyncio"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "no_auth_override: 跳过默认的鉴权覆盖，验证真实的 401/403 行为"
    )


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - 清理临时目录
    import shutil

    shutil.rmtree(_TMP_DIR, ignore_errors=True)


__all__ = ["ROLE_ADMIN", "ROLE_ANALYST", "ROLE_VIEWER"]
