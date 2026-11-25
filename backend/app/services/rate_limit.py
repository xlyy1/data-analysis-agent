"""进程内滑动窗口限流。

单机部署够用；多副本时每个副本各自计数，总量会放大 N 倍——这是刻意的取舍：
真要多副本精确限流应该走 Redis，但项目定位是单机/小规模，引入 Redis 只为计数
不划算。边界写在 docs/architecture.md。
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, int(limit))
        self.window = float(window_seconds)
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def retry_after(self, key: str) -> float:
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return 0.0
            return max(0.0, self.window - (time.monotonic() - bucket[0]))


class KeyedLimiters:
    """按配置懒加载的一组限流器，方便测试里统一 reset。"""

    def __init__(self) -> None:
        self._limiters: dict[str, SlidingWindowLimiter] = {}
        self._lock = threading.Lock()

    def get(self, name: str, limit: int, window_seconds: float = 60.0) -> SlidingWindowLimiter:
        with self._lock:
            limiter = self._limiters.get(name)
            if limiter is None or limiter.limit != limit or limiter.window != window_seconds:
                limiter = SlidingWindowLimiter(limit, window_seconds)
                self._limiters[name] = limiter
            return limiter

    def reset(self) -> None:
        with self._lock:
            for limiter in self._limiters.values():
                limiter.reset()
            self._limiters.clear()


limiters = KeyedLimiters()
