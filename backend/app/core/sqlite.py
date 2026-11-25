"""sqlite3 连接上下文管理器。

`with sqlite3.connect(...) as conn:` 是**事务**上下文，退出时 commit/rollback，
但**不会 close** —— 句柄要等 GC。生产代码里 /readyz、trace.record 都是高频路径，
于是每次探针/每个节点泄漏一个句柄（大量 `ResourceWarning: unclosed database`）。

而 `contextlib.closing` 只关不提交，直接替换会丢掉 commit 语义（试过一次，
4 个 trace 测试立刻失败）。所以这里提供语义等价、且真正关闭连接的版本。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def sqlite_connection(path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(path))
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
