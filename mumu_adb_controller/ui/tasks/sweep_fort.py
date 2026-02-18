# mumu_adb_controller/ui/tasks/sweep_fort.py
import os
import sys
import time
from ..helpers import matcher
from .init_to_wild import run_init_to_wild

# ---------- 冻结安全的资源定位 ----------
try:
    from ...common.pathutil import res_path
except Exception:
    def _app_base_dir():
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    def res_path(*parts: str):
        return os.path.join(_app_base_dir(), *parts)

def _logv(log, msg: str, verbose: bool):
    if verbose:
        log(f"[DEBUG] {msg}")

# 坐标（按你的要求）
P3  = (492, 125)   # 第3步 双击
P4  = (229, 300)   # 第4步 单击
P5  = (356, 572)   # 第5步 双击
P10 = (581, 935)   # 第10步 连续点击

# 图片名
IMG_SHOUCANG = "shoucang.png"
IMG_DAIBAN   = "daiban.png"
IMG_XINGJUN  = "xingjun.png"
IMG_FORT     = "paotai.png"        # 炮台
IMG_CITY     = "wangchegn.png"     # 王城（按你的文件名）
IMG_RED      = "chuzheng_red.png"
IMG_RED2     = "chuzheng_red2.png"  # 备选：阈值固定 0.84
IMG_BLUE2    = "chuzheng_blue_2.png"
IMG_SB       = ["shangbing_1.png", "shangbing_2.png", "shangbing_3.png"]

DEFAULT_STEP_DELAY = 0.10
CLICK_RATE_SLEEP   = 0.06
EXTRA_DELAY_9_10   = 0.30           # 第9和10步之间额外 300ms

def _paths():
    P = lambda n: res_path("pic", n)
    return {
        "shoucang": P(IMG_SHOUCANG),
        "daiban":   P(IMG_DAIBAN),
        "xingjun":  P(IMG_XINGJUN),
        "red":      P(IMG_RED),
        "red2":     P(IMG_RED2),
        "blue2":    P(IMG_BLUE2),
        "fort":     P(IMG_FORT),
        "city":     P(IMG_CITY),
        "sb_list": [P(n) for n in IMG_SB],
    }

def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None

def _sleep_pause(app, sec: float):
    end = time.time() + max(0.0, float(sec))
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        while pause_ev is not None and pause_ev.is_set():
            time.sleep(0.05)
        time.sleep(min(0.1, end - time.time()))

def _delay(app, step_delay: float):
    _sleep_pause(app, step_delay)

def _double_tap(app, serial, x, y, delay=0.12):
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, delay)
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, 0.15)

def _single_tap(app, serial, x, y):
    app.adb.input_tap(serial, x, y)

def _match_one(png_bytes, img_path, threshold=None):
    return matcher.match_one(png_bytes, img_path, threshold=matcher.THRESH if threshold is None else threshold)

def _double_tap_img(app, serial, img_path, log, step_delay: float, threshold, verbose):
    png = _screencap(app, serial)
    if png is None:
        log("[FORT] 截图失败（_double_tap_img）")
        return False, (0, 0)
    ok, (x, y) = _match_one(png, img_path, threshold=threshold)
    _logv(log, f"match {os.path.basename(img_path)} -> {ok}, pos=({x},{y})", verbose)
    if ok:
        _double_tap(app, serial, x, y)
    _delay(app, step_delay)
    return ok, (x, y)

def _single_tap_img(app, serial, img_path, log, step_delay: float, threshold, verbose):
    """单击匹配到的图片"""
    png = _screencap(app, serial)
    if png is None:
        log("[FORT] 截图失败（_single_tap_img）")
        return False, (0, 0)
    ok, (x, y) = _match_one(png, img_path, threshold=threshold)
    _logv(log, f"match {os.path.basename(img_path)} -> {ok}, pos=({x},{y})", verbose)
    if ok:
        _single_tap(app, serial, x, y)
        _sleep_pause(app, 0.15)  # 单击后短暂延时
    _delay(app, step_delay)
    return ok, (x, y)

def _double_tap_img_any(app, serial, img_paths, log, step_delay: float, threshold, verbose):
    png = _screencap(app, serial)
    if png is None:
        log("[FORT] 截图失败（_double_tap_img_any）")
        return False, ("", (0, 0))
    for p in img_paths:
        if os.path.isfile(p):
            ok, (x, y) = _match_one(png, p, threshold=threshold)
            _logv(log, f"match-any {os.path.basename(p)} -> {ok} pos=({x},{y})", verbose)
            if ok:
                _double_tap(app, serial, x, y)
                _delay(app, step_delay)
                return True, (p, (x, y))
    _delay(app, step_delay)
    # 所有图片都不匹配时返回默认值
    return False, ("", (0, 0))


def _double_tap_red_with_fallback(app, serial, paths, log, step_delay: float, threshold, verbose):
    """
    出征红双击：优先 chuzheng_red（阈值=threshold），未命中则尝试 chuzheng_red2（阈值固定 0.84）。
    打印两次匹配得分（detail）。返回 (ok, (x,y), used)；used ∈ {'red','red2','none'}。
    """
    png = _screencap(app, serial)
    if png is None:
        log("[FORT] 截图失败（_double_tap_red_with_fallback）")
        return False, (0, 0), 'none'
    # 主模板
    ok1, pos1, sc1 = matcher.match_one_detail(png, paths["red"], threshold=threshold)
    if ok1:
        _double_tap(app, serial, pos1[0], pos1[1])
        _delay(app, step_delay)
        log(f"[FORT] 命中 red score={sc1:.3f}>=thr={threshold:.2f} → 双击({pos1[0]},{pos1[1]})")
        return True, (pos1[0], pos1[1]), 'red'
    # 备选模板 0.84
    thr2 = 0.84
    ok2, pos2, sc2 = matcher.match_one_detail(png, paths["red2"], threshold=thr2)
    if ok2:
        _double_tap(app, serial, pos2[0], pos2[1])
        _delay(app, step_delay)
        log(f"[FORT] 备选命中 red2 score={sc2:.3f}>=thr={thr2:.2f} → 双击({pos2[0]},{pos2[1]})")
        return True, (pos2[0], pos2[1]), 'red2'
    log(f"[FORT] 未命中 red({sc1:.3f}<thr={threshold:.2f}) & red2({sc2:.3f}<thr={thr2:.2f})")
    _delay(app, step_delay)
    return False, (0, 0), 'none'

def _exist(png_bytes, img_path, threshold) -> bool:
    ok, _ = matcher.match_one(png_bytes, img_path, threshold=threshold)
    return bool(ok)

def _ensure_wild(app, serial, log, paths, should_stop, step_delay: float, threshold, verbose) -> bool:
    """检测是否在野外；若不在，静默调用回到野外（不弹窗）"""
    if should_stop():
        return False
    png = _screencap(app, serial)
    if png is None:
        log("[FORT] 无法截图，终止")
        return False
    in_wild = (
        _exist(png, paths["shoucang"], threshold)
        and _exist(png, paths["daiban"], threshold)
        and _exist(png, paths["xingjun"], threshold)
    )
    _logv(log, f"in_wild={in_wild} thr={threshold}", verbose)
    log(f"[STEP 1] 检测是否在野外：{'是' if in_wild else '否'}")
    if not in_wild:
        log("[STEP 1] 不在野外 → 静默“初始化到野外”")
        def _noop(_): pass
        run_init_to_wild(app, serial, toast=_noop, log=log, threshold=threshold, verbose=verbose)
        _sleep_pause(app, 0.8)
    _delay(app, step_delay)
    return True

def _single_cycle(app, serial, mode: str, seconds: int, log, paths, should_stop, step_delay: float, threshold, verbose):
    """
    执行一次循环：
      1 检测野外（否则回到野外）
      2 双击 收藏图
      3 双击 P3
      4 单击 P4
      5 双击 P5
      6/7 根据模式检查 paotai.png / wangchegn.png 存在；否则回到步骤1
      7 双击 出征红
      8 单击 出征蓝2（已改为单击）
      9 双击 伤兵(任意)
      + 0.3s 额外延时
      10 连续点击 P10（若干秒）
    """
    if should_stop():
        return

    # 1
    if not _ensure_wild(app, serial, log, paths, should_stop, step_delay, threshold, verbose):
        return

    # 2
    log("[STEP 2] 双击 收藏（pic/shoucang.png）")
    ok2, (x2, y2) = _double_tap_img(app, serial, paths["shoucang"], log, step_delay, threshold, verbose)
    log(f"[STEP 2] 结果：{'OK' if ok2 else '未匹配'}；坐标=({x2},{y2})")
    if should_stop(): return

    # 3
    log(f"[STEP 3] 双击坐标 {P3}")
    _double_tap(app, serial, *P3); _delay(app, step_delay)
    if should_stop(): return

    # 4
    log(f"[STEP 4] 单击坐标 {P4}")
    _single_tap(app, serial, *P4); _delay(app, step_delay)
    if should_stop(): return

    # 5
    log(f"[STEP 5] 双击坐标 {P5}")
    _double_tap(app, serial, *P5); _delay(app, step_delay)
    if should_stop(): return

    # 6/7 模式检查图是否存在
    png = _screencap(app, serial)
    if png is None:
        log("[STEP 6] 截图失败，回到步骤1")
        return
    key = "fort" if mode == "fort" else "city"
    chk_path = paths[key]
    okm, _pos = matcher.match_one(png, chk_path, threshold=threshold)
    _logv(log, f"mode-check {('炮台' if key=='fort' else '王城')} -> {okm}", verbose)
    log(f"[STEP 6] 模式检查（{'炮台' if key=='fort' else '王城'}）：{'存在' if okm else '未找到'}")
    if not okm:
        log("[STEP 6] 未找到模式图片 → 回到步骤1")
        return

    # 7 红按钮（支持 red2=0.84 兜底）
    log("[STEP 7] 双击 出征红按钮（red→red2兜底）")
    ok7, (rx, ry), used = _double_tap_red_with_fallback(app, serial, paths, log, step_delay, threshold, verbose)
    log(f"[STEP 7] 结果：{'OK' if ok7 else '未匹配'}；坐标=({rx},{ry})；模板={'red2' if used=='red2' else 'red' if used=='red' else '-'}")
    if should_stop(): return

    # 8 蓝按钮2（改为单击）
    log("[STEP 8] 单击 出征蓝按钮2（pic/chuzheng_blue_2.png）")
    ok8, (bx, by) = _single_tap_img(app, serial, paths["blue2"], log, step_delay, threshold, verbose)
    log(f"[STEP 8] 结果：{'OK' if ok8 else '未匹配'}；坐标=({bx},{by})")
    if should_stop(): return

    # 9 伤兵任意
    log("[STEP 9] 双击 任意伤兵（1/2/3）")
    ok9, (p_hit, (sx, sy)) = _double_tap_img_any(app, serial, paths["sb_list"], log, step_delay, threshold, verbose)
    log(f"[STEP 9] 结果：{'OK' if ok9 else '未匹配'}；命中={os.path.basename(p_hit) if p_hit else '-'}；坐标=({sx},{sy})")

    # 9→10 额外 0.3s
    _sleep_pause(app, EXTRA_DELAY_9_10)

    # 10 连续点击治疗
    log(f"[STEP 10] 连续点击 {P10}，时长 {int(seconds)} 秒（高频连点）")
    end_t = time.time() + max(0, int(seconds))
    while time.time() < end_t:
        if should_stop():
            log("[STEP 10] 停止指令收到（点击阶段），中断本次循环")
            break
        app.adb.input_tap(serial, *P10)
        _sleep_pause(app, CLICK_RATE_SLEEP)
    _delay(app, step_delay)

def run_sweep_fort(app, serial: str, seconds: int, mode: str,
                   toast, log, loop_count: int = 1,
                   should_stop=None, step_delay: float = DEFAULT_STEP_DELAY,
                   threshold: float | None = None,
                   verbose: bool = False):
    """
    刷王城/炮台 主流程（不弹出公告）
      - mode: "fort" 炮台 / "city" 王城（需先在 UI 选择）
      - seconds: 第10步治疗连点时间（每轮）
      - loop_count: 循环次数
      - step_delay: 步与步之间的间隔（调试用）
      - threshold: 匹配阈值（None 使用 matcher.THRESH）
      - verbose: True 输出更多调试信息
    """
    if should_stop is None:
        should_stop = lambda: False

    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    n = max(1, int(loop_count))
    for i in range(1, n + 1):
        if should_stop():
            log("[FORT] 停止指令收到，退出…")
            return
        log(f"[FORT] 循环 {i}/{n} 开始（模式：{'炮台' if mode=='fort' else '王城'}）")
        _single_cycle(app, serial, mode, seconds, log, paths, should_stop, step_delay, thr, verbose)
        log(f"[FORT] 循环 {i}/{n} 结束 → 回到步骤1继续")
    log("[FORT] 全部循环完成")
