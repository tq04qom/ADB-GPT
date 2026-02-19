# mumu_adb_controller/ui/tasks/init_to_wild.py
import os
import time
from ..helpers import matcher
from ..helpers.sleep_utils import friendly_sleep
from ...common.pathutil import res_path

THRESH = matcher.THRESH
MAX_LOOPS = 5

def _logv(log, msg: str, verbose: bool):
    if verbose:
        log(f"[DEBUG] {msg}")

def build_paths():
    """统一从 pic/ 取模板路径（冻结安全）"""
    P = lambda name: res_path("pic", name)
    return {
        "daiban":   P("daiban.png"),
        "xingjun":  P("xingjun.png"),
        "shoucang": P("shoucang.png"),
        "diaoxian": P("diaoxian.png"),
        "haidao":   P("haidao.png"),
        "yewai":    P("yewai.png"),
        "chengzhen": P("chengzhen.png"),
    }

def run_init_to_wild(app, serial: str, toast, log,
                     threshold: float | None = None,
                     verbose: bool = False):
    """
    threshold: 覆盖默认匹配阈值；None 则使用 matcher.THRESH
    verbose:   True 时输出更细的调试日志
    """
    thr = matcher.THRESH if threshold is None else float(threshold)

    if not matcher.has_cv():
        toast("需要依赖：opencv-python 与 numpy。请运行：pip install opencv-python numpy")
        return

    paths = build_paths()

    # 检查模板存在性
    for k, p in paths.items():
        if not os.path.isfile(p):
            toast(f"缺少模板：{p}")
            return

    info = lambda s: log(f"[INIT] {s}")
    warn = lambda s: log(f"[WARN] {s}")

    # 全局速度与模式
    try:
        speed = float(getattr(app, "get_speed_factor", lambda: 1.0)())
    except Exception:
        speed = 1.0
    is_multi = bool(getattr(app, "is_global_multi_mode", lambda: False)())
    _logv(log, f"global speed=x{speed:.2f}, multi={is_multi}", verbose)

    def _sleep(sec: float):
        friendly_sleep(app, sec * speed)

    def screencap() -> bytes | None:
        ok, data = app.adb.screencap(serial)
        if not ok or not data:
            log("[WARN] 截图失败")
            return None
        return data

    info("开始初始化到野外…")
    _logv(log, f"thr={thr}", verbose)

    # 首先发送2次返回键
    info("发送2次返回键…")
    app.adb.input_back(serial)
    _sleep(0.3)
    app.adb.input_back(serial)
    _sleep(0.3)

    scr = screencap()
    if scr is None:
        toast("无法截图，初始化失败")
        return

    if matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
        info("检测到：待办/行军/收藏 同时存在 -> 已处于野外初始化状态")
        toast("已处于野外初始化状态")
        return

    okk, _ = matcher.match_one(scr, paths["diaoxian"], threshold=thr)
    if okk:
        warn("检测到掉线（diaoxian.png）")
        toast("掉线，需手动处理")
        return

    on_island, _ = matcher.match_one(scr, paths["haidao"], threshold=thr)
    if on_island:
        info("检测到海岛，点击 40,33 返回城镇…")
        app.adb.input_tap(serial, 40, 33)
        _sleep(0.3)

        scr = screencap()
        if scr is None:
            toast("无法截图，初始化失败")
            return

        okk, pos = matcher.match_one(scr, paths["yewai"], threshold=thr)
        _logv(log, f"yewai? {okk} pos={pos}", verbose)
        if okk:
            x, y = pos
            info(f"点击 野外按钮 @ ({x},{y})")
            app.adb.input_tap(serial, x, y)
            info("点击 yewai.png 后等待 2.0s 再检测三要素")
            _sleep(2.0)
            scr = screencap()
            if scr is not None and matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
                info("完成：野外初始化")
                return

        info("海岛处理后仍未进入野外，继续回退查找…")

    info("尝试返回并查找野外按钮…")
    app.adb.input_back(serial)
    _sleep(0.3)

    scr = screencap()
    if scr is None:
        toast("无法截图，初始化失败")
        return

    if matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
        toast("已进入野外初始化状态")
        info("完成：野外初始化")
        return

    for i in range(MAX_LOOPS):
        # 检查是否点击了yewai.png或chengzhen.png
        okk_yewai, pos_yewai = matcher.match_one(scr, paths["yewai"], threshold=thr)
        okk_chengzhen, pos_chengzhen = matcher.match_one(scr, paths["chengzhen"], threshold=thr)
        
        _logv(log, f"[loop{i+1}] yewai? {okk_yewai} pos={pos_yewai}, chengzhen? {okk_chengzhen} pos={pos_chengzhen}", verbose)
        
        if okk_yewai:
            x, y = pos_yewai
            info(f"[{i+1}/{MAX_LOOPS}] 点击 野外按钮 @ ({x},{y})")
            app.adb.input_tap(serial, x, y)
            info("点击 yewai.png 后等待 2.0s 再检测三要素")
            _sleep(2.0)
            scr = screencap()
            if scr is not None and matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
                toast("已进入野外初始化状态")
                info("完成：野外初始化")
                return
            continue
        elif okk_chengzhen:
            x, y = pos_chengzhen
            info(f"[{i+1}/{MAX_LOOPS}] 点击 城镇按钮 @ ({x},{y})")
            app.adb.input_tap(serial, x, y)
            _sleep(1.0)  # 点击城镇按钮后等待1000ms
            scr = screencap()
            if scr is not None and matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
                toast("已进入野外初始化状态")
                info("完成：野外初始化")
                return
            continue
        else:
            info(f"[{i+1}/{MAX_LOOPS}] 未找到野外或城镇按钮，发送返回键继续…")
            app.adb.input_back(serial)
            _sleep(0.3)
            scr = screencap()
            if scr is None:
                toast("无法截图，初始化失败")
                return

    warn("仍未进入野外初始化状态")
    toast("初始化失败：未找到“野外”，或进入后未检测到待办/行军/收藏")
