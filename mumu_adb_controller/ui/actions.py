# mumu_adb_controller/ui/actions.py
import os, time
from typing import Dict, Tuple, List, Optional

import numpy as np
try:
    import cv2  # opencv-python
except Exception as e:
    cv2 = None

# 需要匹配的图片（冻结安全路径）
try:
    from ..common.pathutil import res_path
    PIC_DIR = res_path("pic")
except Exception:
    # 兜底：即使 pathutil 未就绪也能在开发与打包环境运行
    import sys
    def _app_base_dir():
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    PIC_DIR = os.path.join(_app_base_dir(), "pic")
REQUIRED_WILD = ["daiban.png", "xingjun.png", "shoucang.png"]
OTHER_SIGNS = ["diaoxian.png", "haidao.png", "yewai.png"]

# 全部模板统一缓存，避免重复读盘
_TEMPLATE_CACHE: Dict[str, np.ndarray] = {}


def _must_cv(logger) -> bool:
    if cv2 is None:
        if logger: logger.error("未安装 opencv-python，请先执行：pip install opencv-python")
        return False
    return True


def _load_template(name: str, logger=None) -> Optional[np.ndarray]:
    """加载模板图到缓存；返回 BGR 图像数组。"""
    path = os.path.join(PIC_DIR, name)
    if name in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[name]
    if not os.path.isfile(path):
        if logger: logger.warn(f"缺少模板：{path}")
        return None
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        if logger: logger.error(f"模板读取失败：{path}")
        return None
    _TEMPLATE_CACHE[name] = img
    return img


def _png_to_mat(png_bytes: bytes) -> Optional[np.ndarray]:
    """将 PNG 字节转 OpenCV BGR Mat（不落盘）。"""
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    mat = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return mat


def _match_one(screen: np.ndarray, templ: np.ndarray, threshold: float = 0.85) -> Optional[Tuple[int,int]]:
    """模板匹配，返回匹配中心坐标 (x,y)；未达阈值返回 None。"""
    # 使用 TM_CCOEFF_NORMED
    res = cv2.matchTemplate(screen, templ, cv2.TM_CCOEFF_NORMED)
    minVal, maxVal, minLoc, maxLoc = cv2.minMaxLoc(res)
    if maxVal < threshold:
        return None
    th, tw = templ.shape[:2]
    x, y = maxLoc[0] + tw // 2, maxLoc[1] + th // 2
    return (x, y)


def _find_many(screen: np.ndarray, names: List[str], threshold: float = 0.85, logger=None) -> Dict[str, Tuple[int,int]]:
    """在 screen 中查找多张模板，返回 {name:(x,y)}（找到的才返回）。"""
    found: Dict[str, Tuple[int,int]] = {}
    for n in names:
        templ = _load_template(n, logger=logger)
        if templ is None:
            continue
        pos = _match_one(screen, templ, threshold=threshold)
        if pos is not None:
            found[n] = pos
    return found


def _is_wild_init(found: Dict[str, Tuple[int,int]]) -> bool:
    """是否达到‘野外初始化状态’（三图齐全）。"""
    return all(f in found for f in REQUIRED_WILD)


def _adb_back(adb, serial: str):
    adb.shell(serial, "input keyevent 4")


def _adb_tap(adb, serial: str, x: int, y: int):
    adb.input_tap(serial, int(x), int(y))


def _capture_screen(adb, serial: str, logger=None) -> Optional[np.ndarray]:
    ok, png = adb.screencap(serial)
    if not ok or not png:
        if logger: logger.warn(f"[{serial}] 截图失败")
        return None
    mat = _png_to_mat(png)
    if mat is None and logger:
        logger.warn(f"[{serial}] 截图解码失败")
    return mat


def initialize_to_wild(adb, serial: str, logger=None, threshold: float = 0.88,
                       max_back_loops: int = 10, post_click_wait: float = 2.0) -> Tuple[bool, str]:
    """
    按需求：初始化到野外
    1) 若已同时存在 daiban/xingjun/shoucang => 已是野外初始化状态
    2) 若 diaoxian => 掉线，提示
    3) 若 haidao => 海岛：点击 (40,33) 返回城镇，1s 后点击 yewai.png
    4) 否则：发送返回键，循环查找 daiban/xingjun/shoucang；若仍不齐，
       则进入“查找 yewai.png – 输出返回键”的循环，直到找到并点击 yewai.png；
       成功后再次校验三图。
    5) 其他情况 => 初始化失败
    """
    if not _must_cv(logger):
        return False, "缺少 opencv-python 依赖"

    # ---------- 初次检查 ----------
    screen = _capture_screen(adb, serial, logger)
    if screen is None:
        return False, "无法截图"
    found = _find_many(screen, REQUIRED_WILD + OTHER_SIGNS, threshold=threshold, logger=logger)

    if _is_wild_init(found):
        return True, "已处于野外初始化状态"

    if "diaoxian.png" in found:
        return False, "检测到掉线（diaoxian.png）"

    # ---------- 海岛分支 ----------
    if "haidao.png" in found:
        if logger: logger.info("检测到海岛（haidao.png），先点击 (40,33) 返回城镇...")
        _adb_tap(adb, serial, 40, 33)
        time.sleep(post_click_wait)
        # 再找 yewai.png
        screen = _capture_screen(adb, serial, logger)
        if screen is None:
            return False, "无法截图（海岛返回后）"
        found2 = _find_many(screen, ["yewai.png"], threshold=threshold, logger=logger)
        if "yewai.png" in found2:
            if logger: logger.info("找到 yewai.png，点击进入野外...")
            x, y = found2["yewai.png"]
            _adb_tap(adb, serial, x, y)
            if logger: logger.info(f"点击 yewai.png 后等待 {post_click_wait:.1f}s 再检测三要素")
            time.sleep(post_click_wait)
            # 校验是否已达成三图
            screen = _capture_screen(adb, serial, logger)
            if screen is None:
                return False, "无法截图（点击野外后）"
            found3 = _find_many(screen, REQUIRED_WILD, threshold=threshold, logger=logger)
            if _is_wild_init(found3):
                return True, "已进入野外初始化状态（海岛返回后）"
            # 未达成则继续走通用流程
        else:
            if logger: logger.warn("未找到 yewai.png（海岛返回后）—继续通用流程")

    # ---------- 通用流程：返回键 + yewai 寻找 ----------
    for i in range(max_back_loops):
        if logger: logger.info(f"返回键尝试第 {i+1}/{max_back_loops} 次...")
        _adb_back(adb, serial)
        time.sleep(0.3)

        screen = _capture_screen(adb, serial, logger)
        if screen is None:
            return False, "无法截图（返回后）"

        # 先看是否已经齐了
        found = _find_many(screen, REQUIRED_WILD, threshold=threshold, logger=logger)
        if _is_wild_init(found):
            return True, "已处于野外初始化状态（返回后）"

        # 不齐则找 yewai.png，找到了就点击
        found_yw = _find_many(screen, ["yewai.png"], threshold=threshold, logger=logger)
        if "yewai.png" in found_yw:
            if logger: logger.info("找到 yewai.png，点击进入野外...")
            x, y = found_yw["yewai.png"]
            _adb_tap(adb, serial, x, y)
            if logger: logger.info(f"点击 yewai.png 后等待 {post_click_wait:.1f}s 再检测三要素")
            time.sleep(post_click_wait)
            # 点击后再校验三图
            screen2 = _capture_screen(adb, serial, logger)
            if screen2 is None:
                return False, "无法截图（点击野外后）"
            found2 = _find_many(screen2, REQUIRED_WILD, threshold=threshold, logger=logger)
            if _is_wild_init(found2):
                return True, "已进入野外初始化状态"
            # 没齐则继续循环；有些界面需要多次 back + 进入

    return False, "初始化失败（未能进入野外）"
