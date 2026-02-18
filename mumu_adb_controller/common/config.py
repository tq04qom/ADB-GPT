import json
import os
from typing import Dict, Any, Optional

# 集中式路径工具（请确保存在）
try:
    from mumu_adb_controller.common.pathutil import (
        app_base_dir,
        res_path,
        user_data_dir,
        ensure_dir,
    )
except Exception:
    # 兜底实现，避免导入失败（打包/开发都可用）
    import sys

    def app_base_dir() -> str:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    def res_path(*parts: str) -> str:
        return os.path.join(app_base_dir(), *parts)

    def ensure_dir(path: str) -> str:
        ap = os.path.abspath(path)
        os.makedirs(ap, exist_ok=True)
        return ap

    def user_data_dir(app_name: str = "MuMuADBController") -> str:
        base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", app_name)
        return ensure_dir(base)


class AppConfig:
    """
    冻结安全 & 便携优先 的配置管理：
    1) 若程序目录下存在 config.json，则优先使用（便携模式，EXE旁存放）。
    2) 否则使用用户数据目录：%APPDATA%/MuMuADBController/config.json

    注意：保存时采用原子写入，避免损坏。
    """

    def __init__(self, app_name: str = "MuMuADBController", filename: str = "config.json"):
        self.app_name = app_name
        self.filename = filename

        # 便携模式探测：程序目录下已有 config.json 就用它
        portable_path = res_path(self.filename)
        if os.path.isfile(portable_path):
            self._base_dir = app_base_dir()
            self._file = portable_path
            self._portable = True
        else:
            self._base_dir = user_data_dir(self.app_name)
            self._file = os.path.join(self._base_dir, self.filename)
            self._portable = False

        # 确保目录存在
        ensure_dir(os.path.dirname(self._file))

    @property
    def file(self) -> str:
        """配置文件的最终路径（可读）。"""
        return self._file

    @property
    def is_portable(self) -> bool:
        """是否处于便携模式（使用程序目录下的 config.json）。"""
        return self._portable

    def load(self) -> Dict[str, Any]:
        """
        读取配置；不存在或解析失败返回 {}。
        """
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception:
            return {}

    def save(self, cfg: Dict[str, Any]) -> bool:
        """
        原子写入保存配置：写临时文件后 os.replace 到目标，避免部分写入。
        """
        try:
            ensure_dir(os.path.dirname(self._file))
            tmp_path = self._file + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg or {}, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._file)
            return True
        except Exception:
            # 尝试清理残留 tmp
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False
