import time
from typing import Callable, Optional


def _should_stop(should_stop: Optional[Callable[[], bool]]) -> bool:
    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except (TypeError, AttributeError):
        return False


def friendly_sleep(app: object, sec: float, should_stop: Optional[Callable[[], bool]] = None) -> None:
    """
    支持全局暂停/停止感知的统一等待函数。
    """
    end = time.time() + max(0.0, float(sec))
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        if _should_stop(should_stop):
            return
        while pause_ev is not None and pause_ev.is_set():
            if _should_stop(should_stop):
                return
            time.sleep(0.05)
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(0.1, remaining))
