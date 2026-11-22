"""批量写入事务测试：整批成功、任一条失败则整批回滚。"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.conversation import Conversation, Message
from app.services.batch import BatchWriteError, bulk_insert_messages


@pytest.fixture()
async def session_factory(tmp_path):
    db = tmp_path / "batch.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture()
async def conversation_id(session_factory):
    async with session_factory() as session:
        conv = Conversation(user_id="u1", title="测试对话")
        session.add(conv)
        await session.commit()
        return conv.id


async def _count_messages(session_factory, conv_id: str) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(Message).where(Message.conversation_id == conv_id)
        )
        return int(result.scalar_one())


@pytest.mark.asyncio
async def test_bulk_insert_commits_whole_batch(session_factory, conversation_id):
    async with session_factory() as session:
        written = await bulk_insert_messages(
            session,
            conversation_id,
            [
                {"role": "user", "content": "近三个月销售额趋势"},
                {"role": "assistant", "content": "已按月份聚合"},
                {"role": "user", "content": "再按门店拆一下"},
            ],
        )

    assert written == 3
    assert await _count_messages(session_factory, conversation_id) == 3


@pytest.mark.asyncio
async def test_bulk_insert_rolls_back_on_bad_row(session_factory, conversation_id):
    """第三条 content 为空 -> 约束失败 -> 前两条也不能留下。"""
    async with session_factory() as session:
        with pytest.raises(BatchWriteError):
            await bulk_insert_messages(
                session,
                conversation_id,
                [
                    {"role": "user", "content": "第一条"},
                    {"role": "user", "content": "第二条"},
                    {"role": "user", "content": None},
                ],
            )

    assert await _count_messages(session_factory, conversation_id) == 0


@pytest.mark.asyncio
async def test_bulk_insert_empty_is_noop(session_factory, conversation_id):
    async with session_factory() as session:
        assert await bulk_insert_messages(session, conversation_id, []) == 0
