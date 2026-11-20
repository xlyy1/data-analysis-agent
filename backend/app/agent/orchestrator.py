"""Sub-agent 调度：把一次请求拆成若干可独立重试的子任务。

角色划分（对应 Harness 里的 supervisor / worker）：
- supervisor：本模块的 dispatch，负责按顺序派发子任务、串起上下文、收集失败；
- sub-agent：一个 SubTask，带自己的超时、重试次数与失败策略。

三条硬约定：
1. 单个子任务失败不拖垮整条链路——失败写进 notes，交给下一个子任务或上层降级；
2. 每次尝试都写一条 trace（node=subagent:<name>），回放时能看到重试轨迹；
3. 超时用 asyncio.wait_for 硬切，避免某个子任务卡死整条请求。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.observability.trace import new_trace_id, record as record_trace

logger = logging.getLogger(__name__)


class SubAgentError(RuntimeError):
    """子任务在重试耗尽后仍未成功。"""

    def __init__(self, name: str, attempts: int, last_error: str):
        super().__init__(f"{name} failed after {attempts} attempt(s): {last_error}")
        self.name = name
        self.attempts = attempts
        self.last_error = last_error


@dataclass
class SubTask:
    """一个可独立执行、独立重试的子任务。"""

    name: str
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    description: str = ""
    max_attempts: int = 2
    timeout_s: float = 120.0
    critical: bool = True  # False 时失败只记 notes，不影响整体


@dataclass
class DispatchResult:
    state: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    attempts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed


def _is_blank(value: Any) -> bool:
    return value in (None, "", [], {})


def looks_failed(state: dict[str, Any]) -> bool:
    """判断一次执行是否「实质失败」。

    有最终回复就算成功（哪怕过程中记了 error），只有「报错且没有回复」或
    「既没有回复也没有澄清问题」才判定失败——避免对可降级结果重复烧模型。
    """
    if not _is_blank(state.get("final_response")):
        return False
    if not _is_blank(state.get("clarification_question")):
        return False
    return True


async def run_subtask(sub: SubTask, state: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
    """执行一个子任务，按 max_attempts 重试；失败抛 SubAgentError。"""
    task_id = task_id or new_trace_id()
    last_error = ""
    for attempt in range(1, sub.max_attempts + 1):
        started = time.time()
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(sub.handler(state), timeout=sub.timeout_s)
            if looks_failed(result):
                last_error = str(result.get("error") or "empty response")
                raise RuntimeError(last_error)
            record_trace(
                task_id,
                f"subagent:{sub.name}",
                "ok",
                started,
                (time.perf_counter() - t0) * 1000,
                fields={"attempt": attempt, "ok": True},
            )
            return result
        except asyncio.TimeoutError:
            last_error = f"timeout after {sub.timeout_s}s"
        except Exception as exc:  # noqa: BLE001 - 失败要能重试或降级
            last_error = f"{type(exc).__name__}: {exc}"
        record_trace(
            task_id,
            f"subagent:{sub.name}",
            "error",
            started,
            (time.perf_counter() - t0) * 1000,
            fields={"attempt": attempt, "ok": False},
            error=last_error,
        )
        logger.warning("subtask %s attempt %s/%s failed: %s", sub.name, attempt, sub.max_attempts, last_error)

    raise SubAgentError(sub.name, sub.max_attempts, last_error)


async def dispatch(
    subtasks: list[SubTask],
    state: dict[str, Any],
    task_id: str | None = None,
    stop_on_first_success: bool = True,
) -> DispatchResult:
    """按顺序派发子任务，成功即返回（默认可降级）。

    stop_on_first_success=True 时表现为「主路径 + 兜底路径」：
    前一个子任务成功就不再执行后面，失败则继续尝试下一个。
    critical=False 的子任务失败只会记 note，不会让整体判定失败。
    """
    task_id = task_id or new_trace_id()
    result = DispatchResult(state=dict(state))
    succeeded = False
    for sub in subtasks:
        try:
            out = await run_subtask(sub, result.state, task_id)
        except SubAgentError as exc:
            result.notes.append(str(exc))
            result.attempts[sub.name] = exc.attempts
            if sub.critical:
                result.failed.append(sub.name)
            continue
        result.state = out
        result.attempts[sub.name] = 1
        succeeded = True
        if stop_on_first_success:
            break
    # 只要有一个子任务交付了结果，整体就算成功：前面的失败已经作为 note 记录（自愈路径）
    if succeeded:
        result.failed = []
    return result
