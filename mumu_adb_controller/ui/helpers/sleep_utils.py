import time
from typing import Callable, Optional


def friendly_sleep(app, sec: float, should_stop: Optional[Callable[[], bool]] = None) -> None:
    """
    支持全局暂停/停止感知的统一等待函数。
    """
    end = time.time() + max(0.0, float(sec))
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        if should_stop is not None:
            try:
                if should_stop():
                    return
            except Exception:
                pass
        while pause_ev is not None and pause_ev.is_set():
            if should_stop is not None:
                try:
                    if should_stop():
                        return
                except Exception:
                    pass
            time.sleep(0.05)
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(0.1, remaining))
