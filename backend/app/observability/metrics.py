"""极简 Prometheus 指标（纯标准库，不引入 prometheus_client）。

为什么自己写：只需要 counter + histogram + gauge 三种，文本格式固定，
少一个依赖就少一次供应链审计和版本冲突。
"""

from __future__ import annotations

import threading
import time
from typing import Iterable

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Metric:
    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text


class Counter(_Metric):
    def __init__(self, name: str, help_text: str = "", labelnames: Iterable[str] = ()) -> None:
        super().__init__(name, help_text)
        self.labelnames = tuple(labelnames)
        self._values: dict[tuple[str, ...], float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(str(labels.get(name, "")) for name in self.labelnames)
        with _lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with _lock:
            items = list(self._values.items())
        for key, value in items:
            label_str = _label_str(self.labelnames, key)
            lines.append(f"{self.name}{label_str} {value:g}")
        return "\n".join(lines)


class Gauge(_Metric):
    def __init__(self, name: str, help_text: str = "", labelnames: Iterable[str] = ()) -> None:
        super().__init__(name, help_text)
        self.labelnames = tuple(labelnames)
        self._values: dict[tuple[str, ...], float] = {}

    def set(self, value: float, **labels: str) -> None:
        key = tuple(str(labels.get(name, "")) for name in self.labelnames)
        with _lock:
            self._values[key] = float(value)

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        with _lock:
            items = list(self._values.items())
        for key, value in items:
            lines.append(f"{self.name}{_label_str(self.labelnames, key)} {value:g}")
        return "\n".join(lines)


class Histogram(_Metric):
    def __init__(
        self,
        name: str,
        help_text: str = "",
        labelnames: Iterable[str] = (),
        buckets: tuple[float, ...] = _BUCKETS,
    ) -> None:
        super().__init__(name, help_text)
        self.labelnames = tuple(labelnames)
        self.buckets = tuple(sorted(buckets))
        self._counts: dict[tuple[str, ...], list[int]] = {}
        self._sums: dict[tuple[str, ...], float] = {}
        self._totals: dict[tuple[str, ...], int] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(str(labels.get(name, "")) for name in self.labelnames)
        with _lock:
            counts = self._counts.setdefault(key, [0] * len(self.buckets))
            for index, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[index] += 1
            self._sums[key] = self._sums.get(key, 0.0) + value
            self._totals[key] = self._totals.get(key, 0) + 1

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with _lock:
            items = list(self._counts.items())
            sums = dict(self._sums)
            totals = dict(self._totals)
        for key, counts in items:
            for index, bound in enumerate(self.buckets):
                lines.append(
                    f"{self.name}_bucket{_label_str(self.labelnames, key, extra=('le', str(bound)))} {counts[index]}"
                )
            lines.append(
                f"{self.name}_bucket{_label_str(self.labelnames, key, extra=('le', '+Inf'))} {totals[key]}"
            )
            lines.append(
                f"{self.name}_sum{_label_str(self.labelnames, key)} {sums[key]:g}"
            )
            lines.append(
                f"{self.name}_count{_label_str(self.labelnames, key)} {totals[key]}"
            )
        return "\n".join(lines)


def _label_str(
    labelnames: tuple[str, ...], values: tuple[str, ...], extra: tuple[str, str] | None = None
) -> str:
    pairs = [f'{name}="{_escape(value)}"' for name, value in zip(labelnames, values, strict=False)]
    if extra:
        pairs.append(f'{extra[0]}="{_escape(extra[1])}"')
    return "{" + ",".join(pairs) + "}" if pairs else ""


# ------------------------------------------------------------------ registry

http_requests_total = Counter(
    "dsh_http_requests_total", "HTTP 请求总数", labelnames=("method", "path", "status")
)
http_request_duration = Histogram(
    "dsh_http_request_duration_seconds", "HTTP 请求耗时（秒）", labelnames=("method", "path")
)
agent_runs_total = Counter(
    "dsh_agent_runs_total", "Agent 分析次数", labelnames=("outcome",)
)
agent_run_duration = Histogram(
    "dsh_agent_run_duration_seconds", "Agent 端到端耗时（秒）"
)
sql_guarded_total = Counter(
    "dsh_sql_guarded_total", "SQL 安全策略拦截次数", labelnames=("reason",)
)
sql_executed_total = Counter(
    "dsh_sql_executed_total", "成功执行的只读 SQL 次数", labelnames=("datasource_type",)
)
schedule_runs_total = Counter(
    "dsh_schedule_runs_total", "定时分析执行次数", labelnames=("status",)
)
task_queue_depth = Gauge("dsh_task_queue_depth", "任务队列积压数")
build_info = Gauge("dsh_build_info", "构建信息", labelnames=("version",))


def render_metrics() -> str:
    blocks = [
        metric.render()
        for metric in (
            http_requests_total,
            http_request_duration,
            agent_runs_total,
            agent_run_duration,
            sql_guarded_total,
            sql_executed_total,
            schedule_runs_total,
            task_queue_depth,
            build_info,
        )
    ]
    return "\n".join(blocks) + "\n"


def observe_http(method: str, path: str, status: int, duration_seconds: float) -> None:
    http_requests_total.inc(method=method, path=path, status=str(status))
    http_request_duration.observe(duration_seconds, method=method, path=path)


class MetricsMiddleware:
    """纯 ASGI 中间件：拿得到路由模板，避免把 id 写进 label 造成基数爆炸。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = "/unmatched"
            route = scope.get("route")
            if route is not None and getattr(route, "path", None):
                path = route.path
            elif scope.get("path") in ("/healthz", "/readyz", "/metrics"):
                path = scope["path"]
            observe_http(
                scope.get("method", "GET"),
                path,
                status_holder["status"],
                time.perf_counter() - started,
            )
