# mumu_adb_controller/ui/tasks/withdraw_troops.py
import os
import sys
import time
from ..helpers import matcher
from .init_to_wild import run_init_to_wild

THRESH = matcher.THRESH
OPERATION_DELAY = 0.3  # 300ms 操作间隔

# ---------- 冻结安全的资源定位 ----------
try:
    from ...common.pathutil import res_path
except Exception:
    # 兜底：即使 pathutil 未就绪也能在开发与打包环境运行
    def _app_base_dir():
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    def res_path(*parts: str):
        return os.path.join(_app_base_dir(), *parts)

def _logv(log, msg: str, verbose: bool):
    if verbose:
        log(f"[DEBUG] {msg}")

def build_paths():
    """统一从 pic/ 取模板路径（冻结安全）"""
    P = lambda name: res_path("pic", name)
    return {
        "withdraw_troops": P("withdraw_troops.png"),
        "confirm": P("confirm.png"),
        "yewai": P("yewai.png"),
        "daiban": P("daiban.png"),
        "xingjun": P("xingjun.png"),
        "shoucang": P("shoucang.png"),
        "fold_marching": P("fold_marching.png"),
    }

def run_withdraw_troops(app, serial: str, toast, log,
                        threshold: float | None = None,
                        verbose: bool = False,
                        should_stop: callable = None):
    """
    一键撤军功能：
    1. 调用回到野外
    2. 确认回到野外后，依次点击 withdraw_troops.png 和 confirm.png
    3. 循环步骤2，直到找不到 withdraw_troops.png
    4. 弹出禁音提示：撤军完成
    每次操作间隔时间300ms

    threshold: 覆盖默认匹配阈值；None 则使用 matcher.THRESH
    verbose:   True 时输出更细的调试日志
    should_stop: 停止检查函数
    """
    thr = matcher.THRESH if threshold is None else float(threshold)

    if not matcher.has_cv():
        toast("需要依赖：opencv-python 与 numpy。请运行：pip install opencv-python numpy")
        return

    # 全局速度与模式
    try:
        speed = float(getattr(app, "get_speed_factor", lambda: 1.0)())
    except Exception:
        speed = 1.0
    is_multi = bool(getattr(app, "is_global_multi_mode", lambda: False)())
    op_delay = OPERATION_DELAY * speed

    def _wait(sec: float):
        end = time.time() + max(0.0, float(sec))
        pause_ev = getattr(app, "pause_event", None)
        while time.time() < end:
            while pause_ev is not None and pause_ev.is_set():
                time.sleep(0.05)
            remaining = end - time.time()
            if remaining > 0:
                time.sleep(min(0.1, remaining))

    paths = build_paths()

    # 检查模板存在性
    for k, p in paths.items():
        if not os.path.isfile(p):
            toast(f"缺少模板：{p}")
            return

    info = lambda s: log(f"[WITHDRAW] {s}")
    warn = lambda s: log(f"[WARN] {s}")

    def screencap() -> bytes | None:
        ok, data = app.adb.screencap(serial)
        if not ok or not data:
            log("[WARN] 截图失败")
            return None
        return data

    def check_stop():
        """检查是否应该停止任务"""
        return should_stop and should_stop()

    info("开始一键撤军…")
    _logv(log, f"thr={thr}", verbose)

    # 步骤1：调用回到野外
    info("步骤1：调用回到野外")

    # 检查是否已经在野外初始化状态
    scr = screencap()
    if scr is None:
        toast("无法截图，撤军失败")
        return

    if not matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
        info("未在野外初始化状态，调用初始化到野外功能…")

        # 使用新的初始化到野外功能
        run_init_to_wild(app, serial, toast, log, threshold=thr, verbose=verbose)

        # 检查是否成功进入野外状态
        scr = screencap()
        if scr is None:
            toast("无法截图，撤军失败")
            return

        if not matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
            warn("初始化到野外失败，撤军终止")
            toast("初始化到野外失败")
            return
    else:
        info("已在野外初始化状态")
    # 野外状态：在 ROI (0,178)-(71,238) 内检测 fold_marching（直接裁剪 ROI 后匹配）
    ok, pos = matcher.match_in_range(scr, paths["fold_marching"], ((0, 178), (71, 238)), threshold=0.90)
    info(f"[WITHDRAW] fold_marching in_roi={ok} pos={pos}")
    if ok:
        x, y = pos
        app.adb.input_tap(serial, int(x), int(y))
        _wait(op_delay)


    # 步骤2-3：循环点击撤军和确认按钮，直到找不到撤军按钮
    info("步骤2-3：开始循环撤军操作")
    withdraw_count = 0

    while True:
        if check_stop():
            info("任务被停止")
            return

        scr = screencap()
        if scr is None:
            toast("无法截图，撤军失败")
            return

        # 检查是否在野外初始化状态
        if not matcher.exist_all(scr, paths, ["daiban", "xingjun", "shoucang"], threshold=thr):
            warn("不在野外初始化状态，撤军终止")
            break

        # 查找撤军按钮
        withdraw_found, withdraw_pos = matcher.match_one(scr, paths["withdraw_troops"], threshold=thr)
        if not withdraw_found:
            info("未找到撤军按钮，撤军完成")
            break

        # 点击撤军按钮
        wx, wy = withdraw_pos
        info(f"点击撤军按钮 @ ({wx},{wy})")
        app.adb.input_tap(serial, wx, wy)
        _wait(op_delay)

        if check_stop():
            info("任务被停止")
            return

        # 查找确认按钮
        scr = screencap()
        if scr is None:
            toast("无法截图，撤军失败")
            return

        confirm_found, confirm_pos = matcher.match_one(scr, paths["confirm"], threshold=thr)
        if confirm_found:
            # 点击确认按钮
            cx, cy = confirm_pos
            info(f"点击确认按钮 @ ({cx},{cy})")
            app.adb.input_tap(serial, cx, cy)
            withdraw_count += 1
            info(f"成功撤军 {withdraw_count} 次")
        else:
            warn("点击撤军按钮后未找到确认按钮")

        _wait(op_delay)

    # 步骤4：弹出禁音提示
    info(f"撤军完成，共撤军 {withdraw_count} 次")
    toast(f"撤军完成，共撤军 {withdraw_count} 次")
