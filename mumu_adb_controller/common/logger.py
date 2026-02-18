import time
from typing import Callable, Optional

class Logger:
    def __init__(self):
        self._sink: Optional[Callable[[str], None]] = None

    def set_sink(self, sink: Callable[[str], None]):
        self._sink = sink

    def _emit(self, level: str, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {level}: {msg}"
        if self._sink:
            try: self._sink(line)
            except Exception: pass
        else:
            print(line)

    def info(self, msg: str): self._emit("INFO", msg)
    def warn(self, msg: str): self._emit("WARN", msg)
    def error(self, msg: str): self._emit("ERROR", msg)
