from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol


class StopChecker(Protocol):
    def __call__(self) -> bool: ...


@dataclass(frozen=True)
class TaskContext:
    """
    任务统一上下文（适配层）。
    说明：仅聚合现有调用参数，不改变现有任务行为。
    """
    app: object
    serial: str
    toast: Callable[[str], None]
    log: Callable[[str], None]
    should_stop: StopChecker
    threshold: Optional[float] = None
    verbose: bool = False
