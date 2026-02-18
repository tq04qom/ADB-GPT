# mumu_adb_controller/ui/tasks/sweep_army.py
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

# 坐标
P4 = (492, 125)
P5 = (229, 300)   # 第5步：单击
P6 = (361, 635)
P8 = (284, 120)
P11 = (584, 925)  # 连续点击坐标（治疗按钮）

IMG_SHOUCANG = "shoucang.png"
IMG_CHUZHENG_BLUE = "chuzheng_blue.png"
IMG_CHUZHENG_BLUE2 = "chuzheng_blue_2.png"
IMG_SB = ["shangbing_1.png", "shangbing_2.png", "shangbing_3.png"]

# 默认步间延时（秒）；可被 run_sweep_army(..., step_delay=) 覆盖
DEFAULT_STEP_DELAY = 0.10
CLICK_RATE_SLEEP = 0.06  # 第11步连点节奏（约16次/秒）
EXTRA_DELAY_10_11 = 0.30  # 第10 → 第11 之间的额外延时
SHANGBING_THRESHOLD = 0.75  # 伤兵图标专用阈值（降低到0.75以提高识别率）
STEP9_TO_STEP10_DELAY = 2.0  # STEP 9→10 之间的等待时间（秒）
STEP10_MAX_RETRY = 3  # STEP 10 最大重试次数

def _paths():
    P = lambda n: res_path("pic", n)
    return {
        "shoucang": P(IMG_SHOUCANG),
        "chuzheng_blue": P(IMG_CHUZHENG_BLUE),
        "chuzheng_blue_2": P(IMG_CHUZHENG_BLUE2),
        "sb_list": [P(n) for n in IMG_SB],
        "daiban": P("daiban.png"),
        "xingjun": P("xingjun.png"),
    }

def _screencap(app, serial, retry=3):
    """截图，支持重试机制"""
    for attempt in range(retry):
        ok, data = app.adb.screencap(serial)
        if ok and data is not None:
            return data
        if attempt < retry - 1:
            time.sleep(0.2)  # 重试前等待0.2秒
    return None

def _sleep_pause(app, sec: float):
    end = time.time() + max(0.0, float(sec))
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        while pause_ev is not None and pause_ev.is_set():
            time.sleep(0.05)
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(0.1, remaining))

def _delay_step(app, step_delay: float):
    _sleep_pause(app, step_delay)

def _double_tap(app, serial, x, y, delay=0.12):
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, delay)
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, 0.15)

def _single_tap(app, serial, x, y):
    app.adb.input_tap(serial, x, y)

def _double_tap_img(app, serial, img_path, threshold, log, verbose):
    png = _screencap(app, serial)
    if png is None:
        _logv(log, "screencap failed in _double_tap_img", verbose)
        return (False, (0, 0))
    ok, pos = matcher.match_one(png, img_path, threshold=threshold)
    _logv(log, f"match {os.path.basename(img_path)} -> {ok}, pos={pos}", verbose)
    if not ok:
        return (False, (0, 0))
    x, y = pos
    _double_tap(app, serial, x, y)
    return (True, (x, y))

def _single_tap_img(app, serial, img_path, threshold, log, verbose):
    png = _screencap(app, serial)
    if png is None:
        _logv(log, "screencap failed in _single_tap_img", verbose)
        return (False, (0, 0))
    ok, pos = matcher.match_one(png, img_path, threshold=threshold)
    _logv(log, f"match {os.path.basename(img_path)} -> {ok}, pos={pos}", verbose)
    if not ok:
        return (False, (0, 0))
    x, y = pos
    app.adb.input_tap(serial, x, y)  # 单击
    return (True, (x, y))

def _double_tap_img_any(app, serial, img_paths, threshold, log, verbose, shangbing_threshold=None):
    """尝试匹配任意一个图片，伤兵图标使用专用阈值"""
    # 首先检查所有图片文件是否存在
    missing_files = [p for p in img_paths if not os.path.isfile(p)]
    if missing_files:
        log(f"[WARN] 以下图片文件不存在: {[os.path.basename(f) for f in missing_files]}")

    for p in img_paths:
        if os.path.isfile(p):
            # 伤兵图标使用专用阈值
            use_threshold = shangbing_threshold if shangbing_threshold is not None else threshold
            _logv(log, f"尝试匹配 {os.path.basename(p)}，阈值={use_threshold}", verbose)
            ok, pos = _double_tap_img(app, serial, p, use_threshold, log, verbose)
            if ok:
                log(f"[SUCCESS] 匹配成功: {os.path.basename(p)}，坐标={pos}")
                return (True, (p, pos))
            else:
                _logv(log, f"匹配失败: {os.path.basename(p)}", verbose)
    return (False, ("", (0, 0)))

def _ensure_wild(app, serial, toast, log, paths, should_stop, step_delay: float, threshold, verbose):
    """检测是否在野外；若不在，静默调用回到野外，并检查是否成功"""
    if should_stop(): return False
    png = _screencap(app, serial)
    if png is None:
        app.after(0, lambda: toast("无法截图，终止"))
        return False

    log("[STEP 2] 检测是否在野外（期望看到 shoucang.png / daiban.png / xingjun.png）")
    in_wild = matcher.exist_all(png, paths, ["shoucang", "daiban", "xingjun"], threshold=threshold)
    _logv(log, f"in_wild={in_wild} thr={threshold}", verbose)
    
    if not in_wild:
        log("[STEP 2] 不在野外 -> 静默调用回到野外流程（不弹窗）")
        def _noop(_): pass
        run_init_to_wild(app, serial, toast=_noop, log=log, threshold=threshold, verbose=verbose)
        _sleep_pause(app, 0.8)

        # 再次检测是否成功回到野外
        png = _screencap(app, serial)
        if png is None:
            log("[STEP 2] 回到野外后无法截图，跳过本次循环")
            return False
            
        in_wild_after = matcher.exist_all(png, paths, ["shoucang", "daiban", "xingjun"], threshold=threshold)
        _logv(log, f"回到野外后检测结果: in_wild={in_wild_after}", verbose)
        
        if not in_wild_after:
            log("[STEP 2] 回到野外失败，跳过本次循环")
            return False
    
    _delay_step(app, step_delay)
    return True

def _single_cycle(app, serial, seconds, log, paths, should_stop, step_delay: float, threshold, verbose, is_first_cycle=False, heal_count=0):
    """
    执行一次从步骤 2 到 11 的完整流程，返回 (success: bool, need_restart: bool)

    is_first_cycle: 是否为首次循环
    heal_count: 单次治疗数量（仅在首次循环时使用）
    """
    if should_stop(): return (False, False)

    # 3. 双击 pic/shoucang.png
    log("[STEP 3] 双击 收藏（pic/shoucang.png）")
    ok, (x, y) = _double_tap_img(app, serial, paths["shoucang"], threshold, log, verbose)
    log(f"[STEP 3] 结果：{'OK' if ok else '未匹配'}；坐标=({x},{y})")
    _delay_step(app, step_delay)

    # 4. 双击 P4
    log(f"[STEP 4] 双击坐标 P4={P4}")
    _double_tap(app, serial, *P4)
    _delay_step(app, step_delay)

    # 5. 单击 P5
    log(f"[STEP 5] 单击坐标 P5={P5}")
    _single_tap(app, serial, *P5)
    _delay_step(app, step_delay)

    # 6. 双击 P6
    log(f"[STEP 6] 双击坐标 P6={P6}")
    _double_tap(app, serial, *P6)
    _delay_step(app, step_delay)

    # 7. 双击 出征蓝1
    log("[STEP 7] 双击 出征蓝按钮（pic/chuzheng_blue.png）")
    ok1, (x1, y1) = _double_tap_img(app, serial, paths["chuzheng_blue"], threshold, log, verbose)
    log(f"[STEP 7] 结果：{'OK' if ok1 else '未匹配'}；坐标=({x1},{y1})")
    _delay_step(app, step_delay)

    # 8. 双击 P8
    log(f"[STEP 8] 双击坐标 P8={P8}")
    _double_tap(app, serial, *P8)
    _delay_step(app, step_delay)

    # 9. 单击 出征蓝2
    log("[STEP 9] 单击 出征蓝按钮2（pic/chuzheng_blue_2.png）")
    ok2, (x2, y2) = _single_tap_img(app, serial, paths["chuzheng_blue_2"], threshold, log, verbose)
    log(f"[STEP 9] 结果：{'OK' if ok2 else '未匹配'}；坐标=({x2},{y2})")
    _delay_step(app, step_delay)

    # STEP 9 → STEP 10 之间等待，让界面加载完成
    log(f"[STEP 9→10] 等待{STEP9_TO_STEP10_DELAY}秒，让界面加载完成")
    _sleep_pause(app, STEP9_TO_STEP10_DELAY)

    # 10. 双击 任意伤兵图（1/2/3）- 使用专用阈值，支持重试
    log(f"[STEP 10] 尝试打开任意伤兵条目（pic/shangbing_1/2/3.png 任意一个，阈值={SHANGBING_THRESHOLD}）")

    ok3 = False
    p_hit = ""
    sx, sy = 0, 0

    # 重试机制：最多尝试STEP10_MAX_RETRY次
    for retry_count in range(STEP10_MAX_RETRY):
        if retry_count > 0:
            log(f"[STEP 10] 第 {retry_count + 1}/{STEP10_MAX_RETRY} 次尝试")
            _sleep_pause(app, 0.5)  # 重试前等待0.5秒

        # 保存调试截图（仅第一次尝试）
        if retry_count == 0:
            try:
                png = _screencap(app, serial)
                if png is not None:
                    import cv2
                    timestamp = int(time.time())
                    debug_path = f"debug_step10_{timestamp}.png"
                    cv2.imwrite(debug_path, png)
                    log(f"[DEBUG] 已保存STEP 10调试截图: {debug_path}")
            except Exception as e:
                _logv(log, f"保存调试截图失败: {e}", verbose)

        ok3, (p_hit, (sx, sy)) = _double_tap_img_any(
            app, serial, paths["sb_list"], threshold, log, verbose,
            shangbing_threshold=SHANGBING_THRESHOLD
        )

        if ok3:
            log(f"[STEP 10] 成功！命中图片={os.path.basename(p_hit)}；坐标=({sx},{sy})")
            break
        else:
            log(f"[STEP 10] 第 {retry_count + 1} 次尝试失败，未找到伤兵图标")

    # 如果所有重试都失败，返回需要重启标志
    if not ok3:
        log(f"[STEP 10] 所有 {STEP10_MAX_RETRY} 次尝试均失败，将等待 {int(seconds)} 秒后重新从STEP 2开始")
        return (False, True)  # (success=False, need_restart=True)

    _delay_step(app, step_delay)

    # 首次循环特殊处理：快速选择0个伤兵 + 输入治疗数量
    if is_first_cycle:
        log("[FIRST CYCLE] 首次循环特殊处理开始")

        # 快速选择0个伤兵（最多重试3次）
        quick_select_success = False
        for quick_select_retry in range(3):
            log(f"[FIRST CYCLE] 快速选择0个伤兵 - 第 {quick_select_retry + 1}/3 次尝试")

            # 点击3次快速选择，间隔0.5秒
            for i in range(3):
                _single_tap(app, serial, 122, 931)
                _sleep_pause(app, 0.5)

            # 等待界面更新
            _sleep_pause(app, 0.5)

            # 检查是否找到pic/0_shangbing.png
            png = _screencap(app, serial)
            if png is not None:
                # 添加0_shangbing.png到paths
                zero_shangbing_path = res_path("pic", "0_shangbing.png")
                if os.path.isfile(zero_shangbing_path):
                    ok_zero, _ = matcher.match_one(png, zero_shangbing_path, threshold=threshold)
                    if ok_zero:
                        log("[FIRST CYCLE] 成功找到0个伤兵标记")
                        quick_select_success = True
                        break

            if quick_select_retry < 2:
                log("[FIRST CYCLE] 未找到0个伤兵标记，回到野外重试")
                # 回到野外
                if not _ensure_wild(app, serial, None, log, paths, should_stop, step_delay, threshold, verbose):
                    log("[FIRST CYCLE] 回到野外失败")
                    return (False, True)
                # 重新双击伤兵图标
                ok3, (p_hit, (sx, sy)) = _double_tap_img_any(
                    app, serial, paths["sb_list"], threshold, log, verbose,
                    shangbing_threshold=SHANGBING_THRESHOLD
                )
                if not ok3:
                    log("[FIRST CYCLE] 重新双击伤兵图标失败")
                    return (False, True)
                _sleep_pause(app, STEP9_TO_STEP10_DELAY)

        if not quick_select_success:
            log("[FIRST CYCLE] 连续3次无法找到0个伤兵标记，停止任务")
            return (False, False)

        # 输入治疗数量
        if heal_count > 0:
            log(f"[FIRST CYCLE] 输入治疗数量: {heal_count}")
            _single_tap(app, serial, 541, 398)  # 点击伤兵输入坐标1
            _sleep_pause(app, 0.2)
            app.adb.input_text(serial, str(heal_count))
            _sleep_pause(app, 0.5)
            log(f"[FIRST CYCLE] 已输入治疗数量: {heal_count}")

        log("[FIRST CYCLE] 首次循环特殊处理完成")

    # 第10 → 第11 之间额外 0.3s 延迟
    _sleep_pause(app, EXTRA_DELAY_10_11)

    # 11. 连续点击 P11
    log(f"[STEP 11] 连续点击坐标 P11={P11}，时长 {int(seconds)} 秒（点击频率约 ~16 次/秒）")
    end_t = time.time() + max(0, int(seconds))
    click_count = 0
    while time.time() < end_t:
        if should_stop():
            log("[STEP 11] 停止指令收到（点击阶段），中断本次循环")
            break
        app.adb.input_tap(serial, *P11)
        click_count += 1
        _sleep_pause(app, CLICK_RATE_SLEEP)
    log(f"[STEP 11] 完成，共点击 {click_count} 次")
    _delay_step(app, step_delay)

    return (True, False)  # (success=True, need_restart=False)

def _parse_beijing_time(time_str: str) -> float:
    """
    解析北京时间字符串 (HH:MM) 为时间戳
    返回距离该时间的秒数（如果时间已过，返回0）
    """
    try:
        if not time_str or ":" not in time_str:
            return 0

        import datetime
        parts = time_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])

        # 获取当前北京时间
        now = datetime.datetime.now()

        # 创建目标时间（今天的指定时间）
        target_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)

        # 如果目标时间已过，则使用明天的该时间
        if target_time <= now:
            target_time += datetime.timedelta(days=1)

        # 计算距离目标时间的秒数
        delta = target_time - now
        return delta.total_seconds()
    except Exception:
        return 0


def run_sweep_army(app, serial: str, seconds: int, toast, log,
                   loop_count: int = 1, total_duration: int = 0,
                   should_stop=None, step_delay: float = DEFAULT_STEP_DELAY,
                   threshold: float | None = None,
                   verbose: bool = False,
                   stop_time: str = "",
                   heal_count: int = 0):
    """
    刷全军主流程（设备工作线程中运行）
    - seconds：STEP 11 连续点击 P11 的时长（每次循环）
    - loop_count：循环次数（>0 生效；若 total_duration>0，则忽略 loop_count）
    - total_duration：总时长（秒，>0 时优先生效）
    - should_stop：回调（无参 -> bool），返回 True 时停止
    - step_delay：步间延时（秒），调试用（默认 0.10s）
    - threshold：匹配阈值（None 使用 matcher.THRESH）
    - verbose：True 输出更详细的调试日志
    - stop_time：停止时间（北京时间，HH:MM 格式，如 "7:00"），当到达指定时间时停止
    - heal_count：单次治疗数量（仅在首次循环时使用）

    循环逻辑：每次循环从 STEP 2 开始，执行到 STEP 11，然后再次回到 STEP 2。
    """
    if should_stop is None:
        should_stop = lambda: False

    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    # 解析停止时间（北京时间）
    stop_time_seconds = _parse_beijing_time(stop_time)
    if stop_time_seconds > 0:
        log(f"[SWEEP] 停止时间设置为北京时间 {stop_time}，距离现在 {int(stop_time_seconds)} 秒")
        total_duration = stop_time_seconds

    # 记录是否为首次循环
    is_first_cycle = True
    start_time = time.time()

    if total_duration and total_duration > 0:
        # 按总时长循环（北京时间模式）
        while True:
            if should_stop():
                log("[SWEEP] 停止指令收到（北京时间模式），退出…")
                return

            # 检查是否到达停止时间
            elapsed = time.time() - start_time
            if elapsed >= total_duration:
                log(f"[SWEEP] 已到达停止时间，退出…")
                break

            if not _ensure_wild(app, serial, toast, log, paths, should_stop, step_delay, thr, verbose):
                log("[SWEEP] 回到野外失败，跳过本次循环，继续下一个循环")
                continue

            success, need_restart = _single_cycle(
                app, serial, seconds, log, paths, should_stop, step_delay, thr, verbose,
                is_first_cycle=is_first_cycle, heal_count=heal_count
            )
            is_first_cycle = False  # 标记首次循环已完成

            if need_restart:
                # STEP 10失败，等待[持续秒数]后重新从STEP 2开始
                log(f"[SWEEP] 等待 {int(seconds)} 秒后重新启动…")
                _sleep_pause(app, seconds)
                continue
            log("[SWEEP] 本次循环完成，回到第二步继续…")
    else:
        # 按次数循环
        n = max(1, int(loop_count))
        for i in range(1, n+1):
            if should_stop():
                log("[SWEEP] 停止指令收到（按次数模式），退出…")
                return
            log(f"[SWEEP] 循环 {i}/{n} 开始")
            if not _ensure_wild(app, serial, toast, log, paths, should_stop, step_delay, thr, verbose):
                log("[SWEEP] 回到野外失败，跳过本次循环，继续下一个循环")
                continue

            success, need_restart = _single_cycle(
                app, serial, seconds, log, paths, should_stop, step_delay, thr, verbose,
                is_first_cycle=is_first_cycle, heal_count=heal_count
            )
            is_first_cycle = False  # 标记首次循环已完成

            if need_restart:
                # STEP 10失败，等待[持续秒数]后重新从STEP 2开始
                log(f"[SWEEP] 等待 {int(seconds)} 秒后重新启动…")
                _sleep_pause(app, seconds)
                continue
            log(f"[SWEEP] 循环 {i}/{n} 完成，回到第二步继续…")

    log("[SWEEP] 全部循环完成")
