import threading, queue
from typing import Callable

class DeviceWorker:
    def __init__(self, serial: str, adb, logger):
        self.serial = serial
        self.adb = adb
        self.logger = logger
        self._q: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._thr = threading.Thread(target=self._run, name=f"Worker-{serial}", daemon=True)
        self._stop = threading.Event()
        self.idle = True

    def start(self):
        if not self._thr.is_alive():
            self._thr.start()

    def stop(self):
        self._stop.set()
        try: self._q.put_nowait(lambda: None)
        except Exception: pass

    def submit(self, fn: Callable[[], None]):
        try: self._q.put_nowait(fn)
        except Exception: self.logger.error(f"[{self.serial}] 提交任务失败")

    def _run(self):
        while not self._stop.is_set():
            try:
                fn = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.idle = False
                fn()
            except Exception as e:
                self.logger.error(f"[{self.serial}] 任务错误：{e}")
            finally:
                self.idle = True
