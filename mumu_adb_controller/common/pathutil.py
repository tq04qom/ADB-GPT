# mumu_adb_controller/common/pathutil.py
import os, sys
from functools import lru_cache

@lru_cache(maxsize=1)
def app_base_dir() -> str:
    """
    冻结安全：开发态返回 main.py 所在目录；PyInstaller 打包后返回 _MEIPASS。
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    # sys.argv[0] 更贴近“可执行入口”的目录，比 __file__ 更适合资源定位
    return os.path.dirname(os.path.abspath(sys.argv[0]))

def res_path(*parts: str) -> str:
    """
    统一的资源定位：res_path('pic','xxx.png')
    """
    return os.path.join(app_base_dir(), *parts)

def ensure_dir(path: str) -> str:
    """
    确保目录存在（返回绝对路径）。可用于日志/缓存/导出等路径。
    """
    ap = os.path.abspath(path)
    os.makedirs(ap, exist_ok=True)
    return ap

def user_data_dir(app_name: str = "MuMuADBController") -> str:
    """
    推荐把可写文件放到用户数据目录（避免 Program Files 无权限）。
    """
    base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", app_name)
    return ensure_dir(base)
