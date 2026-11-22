"""批量写入：一批要么全成功，要么整批回滚。

单条逐次 commit 的问题是中途失败会留下半截数据（比如一批消息只写进去前 3 条），
调用方还得自己清理。这里改成「攒够一批 -> flush -> 一次 commit」，任何一条失败
就 rollback，调用方拿到异常时库里不会多出半批脏数据。
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Message


class BatchWriteError(RuntimeError):
    """整批写入失败，已回滚。"""


async def bulk_insert_messages(
    session: AsyncSession,
    conversation_id: str,
    items: Iterable[dict],
    *,
    batch_size: int = 200,
) -> int:
    """一次事务写入多条消息，返回写入条数。

    items 里每项至少包含 role 与 content；任一条违反约束（如 content 为空）
    都会让整批回滚，不会留下半批数据。
    """
    rows = list(items)
    if not rows:
        return 0

    written = 0
    try:
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            session.add_all(
                [
                    Message(
                        conversation_id=conversation_id,
                        role=item["role"],
                        content=item["content"],
                        metadata_json=item.get("metadata"),
                    )
                    for item in chunk
                ]
            )
            # flush 触发约束校验，失败立刻抛，不必等到 commit
            await session.flush()
            written += len(chunk)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        raise BatchWriteError(f"批量写入失败，已回滚 {written} 条：{exc}") from exc

    return written
