# mumu_adb_controller/core/adb.py
import os
import sys
import subprocess
from typing import List, Tuple, Optional
from ..common.logger import Logger

# ---- 冻结安全 res_path：优先用集中管理的 pathutil，失败则本地兜底 ----
try:
    from ..common.pathutil import res_path
except Exception:
    def _app_base_dir() -> str:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS  # PyInstaller 解包目录
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    def res_path(*parts: str) -> str:
        return os.path.join(_app_base_dir(), *parts)


class AdbClient:
    """
    简易 ADB 封装（冻结安全路径）。
    - 默认 adb 路径使用 res_path('adb','adb.exe')；
    - 若不存在则回退到系统 PATH 中的 adb/adb.exe；
    - 通过 set_adb_path 可随时覆盖。
    """
    def __init__(self, adb_path: Optional[str], logger: Logger):
        self.logger = logger
        self.adb_path: Optional[str] = None

        # 优先使用传入的路径，否则使用默认路径
        if adb_path and os.path.isfile(adb_path):
            self.set_adb_path(adb_path)
        else:
            # 尝试多种可能的ADB路径
            possible_paths = [
                res_path("adb", "adb.exe"),  # 打包后的路径
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "adb", "adb.exe"),  # 开发环境路径
                "adb.exe"  # 系统PATH中的adb
            ]
            
            for path in possible_paths:
                if os.path.isfile(path):
                    self.set_adb_path(path)
                    break
            else:
                # 如果所有路径都找不到，使用默认路径并让set_adb_path处理错误
                self.set_adb_path(adb_path or res_path("adb", "adb.exe"))

    # ---------------- 配置 ----------------
    def set_adb_path(self, path: Optional[str]) -> Tuple[bool, str]:
        """
        设置/切换 adb 路径：
        1) 优先使用传入 path（若是文件存在）；
        2) 否则使用 res_path('adb','adb.exe')；
        3) 若仍不存在，回退到系统 PATH 的 adb/adb.exe，并验证 version。
        """
        # 情况 1：显式给了有效文件
        if path and os.path.isfile(path):
            self.adb_path = os.path.abspath(path)
            ok, out = self._run(["version"])
            if ok:
                return True, f"使用 ADB：{self.adb_path}"
            else:
                msg = f"ADB 无法运行：{self.adb_path}\n{out}"
                self.logger.error(msg)
                return False, msg

        # 情况 2：项目内内置 adb
        packaged = res_path("adb", "adb.exe")
        if os.path.isfile(packaged):
            self.adb_path = packaged
            ok, out = self._run(["version"])
            if ok:
                return True, f"使用内置 ADB：{self.adb_path}"
            else:
                msg = f"ADB 无法运行：{self.adb_path}\n{out}"
                self.logger.error(msg)
                return False, msg

        # 情况 3：系统 PATH
        self.adb_path = "adb.exe" if os.name == "nt" else "adb"
        ok, out = self._run(["version"])
        if ok:
            self.logger.info(f"使用系统 PATH 中的 adb：{self.adb_path}")
            return True, f"使用系统 PATH 中的 adb：{self.adb_path}"
        else:
            self.adb_path = None
            msg = "未找到可用的 adb：请在设置中选择 adb.exe，或确保已安装 platform-tools 并加入 PATH"
            self.logger.error(msg)
            return False, msg

    # ---------------- helpers ----------------
    def _run(self, args: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """
        执行 adb 子进程，返回 (ok, stdout+stderr)。
        在 Windows 下隐藏黑窗。
        """
        if not self.adb_path:
            return False, "adb path not set"

        try:
            cmd = [self.adb_path] + args
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            p = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                creationflags=creation
            )
            out = p.stdout.decode("utf-8", errors="ignore").strip()
            ok = (p.returncode == 0)
            return ok, out
        except subprocess.TimeoutExpired:
            return False, "ADB 命令超时"
        except Exception as e:
            return False, f"ADB 执行失败：{e}"

    # ---------------- 设备管理 ----------------
    def list_devices(self) -> List[str]:
        ok, out = self._run(["devices"])
        if not ok:
            self.logger.error(f"列出设备失败：{out}")
            return []
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        res: List[str] = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                res.append(parts[0])
        return res

    def connect(self, ip_port: str):
        # 缩短连接超时，避免大规模扫描时长时间卡住
        return self._run(["connect", ip_port], timeout=2)

    def disconnect(self, serial: str):
        return self._run(["disconnect", serial], timeout=2)

    # ---------------- 输入事件 ----------------
    def shell(self, serial: str, cmd: str):
        return self._run(["-s", serial, "shell", cmd])

    def input_tap(self, serial: str, x: int, y: int):
        return self.shell(serial, f"input tap {x} {y}")

    def input_text(self, serial: str, text: str):
        safe = text.replace(" ", "%s")
        return self.shell(serial, f"input text {safe}")

    def input_keyevent(self, serial: str, keycode: int):
        return self.shell(serial, f"input keyevent {keycode}")

    def input_back(self, serial: str):
        # KEYCODE_BACK = 4
        return self.input_keyevent(serial, 4)

    def input_swipe(self, serial: str, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 1000):
        """执行滑动操作"""
        return self.shell(serial, f"input swipe {start_x} {start_y} {end_x} {end_y} {duration}")

    # ---------------- 截图（PNG bytes） ----------------
    def screencap(self, serial: str):
        """
        返回 (ok, png_bytes|None)
        """
        if not self.adb_path:
            return False, None
        try:
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            cmd = [self.adb_path, "-s", serial, "exec-out", "screencap", "-p"]
            p = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                creationflags=creation
            )
            if p.returncode != 0:
                return False, None
            return True, p.stdout
        except subprocess.TimeoutExpired:
            return False, None
        except Exception:
            return False, None
