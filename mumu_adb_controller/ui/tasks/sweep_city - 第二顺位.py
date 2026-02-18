# mumu_adb_controller/ui/tasks/sweep_city.py
"""
刷王城模式 - 全新实现
支持五个目标：北地炮台、西城炮台、南翼炮台、东城炮台、太阳城
"""
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

# 目标坐标映射
TARGET_COORDS = {
    "north": (604, 604),  # 北地炮台
    "west": (594, 604),   # 西城炮台
    "south": (594, 594),  # 南翼炮台
    "east": (604, 594),   # 东城炮台
    "sun": (597, 597),    # 太阳城
}

# 目标图片映射
TARGET_IMAGES = {
    "north": "beipaotai.png",    # 北地炮台
    "west": "xipaotai.png",      # 西城炮台
    "south": "nanpaotai.png",    # 南翼炮台
    "east": "dongpaotai.png",    # 东城炮台
    "sun": "taiyangcheng.png",   # 太阳城
}

# 目标中文名称
TARGET_NAMES = {
    "north": "北地炮台",
    "west": "西城炮台",
    "south": "南翼炮台",
    "east": "东城炮台",
    "sun": "太阳城",
}

# 检测区域
DETECT_REGION = ((220, 1029), (519, 1109))

# 出征按钮尝试坐标（仅保留第1坐标）
ATTACK_CENTER_COORDS = [
    (350, 580),  # 第1坐标
]

# 队伍选择坐标
TEAM_COORDS = [
    (66, 118),   # 1队
    (140, 118),  # 2队
]

# 出征蓝按钮检测区域（扩大范围以确保能找到蓝按钮）
BLUE_BUTTON_REGION = ((200, 1000), (800, 1280))

# 伤兵检测区域
SOLDIER_REGION = ((461, 773), (615, 1085))

# 治疗按钮坐标
HEAL_BUTTON = (581, 935)

# 图片文件
IMG_SHOUCANG = "shoucang.png"
IMG_RED2 = "chuzheng_red2.png"
IMG_BLUE2 = "chuzheng_blue_2.png"
IMG_SOLDIERS = ["shangbing_1.png", "shangbing_2.png", "shangbing_3.png"]

# 时间常量
CLICK_RATE = 20  # 每秒点击次数
CLICK_INTERVAL = 1.0 / CLICK_RATE  # 点击间隔

def _paths():
    P = lambda n: res_path("pic", n)
    return {
        "shoucang": P(IMG_SHOUCANG),
        "red2": P(IMG_RED2),
        "blue2": P(IMG_BLUE2),
        "soldiers": [P(n) for n in IMG_SOLDIERS],
        "targets": {k: P(v) for k, v in TARGET_IMAGES.items()},
    }

def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None

def _sleep_pause(app, sec: float):
    """支持暂停的延时"""
    end = time.time() + max(0.0, float(sec))
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        while pause_ev is not None and pause_ev.is_set():
            time.sleep(0.05)
        time.sleep(min(0.1, end - time.time()))

def _tap(app, serial, x, y):
    """单击"""
    app.adb.input_tap(serial, x, y)

def _double_tap(app, serial, x, y):
    """双击"""
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, 0.12)
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, 0.15)

def _send_back(app, serial):
    """发送返回键"""
    app.adb.input_keyevent(serial, 4)

def _send_delete(app, serial, count=1):
    """发送删除键"""
    for _ in range(count):
        app.adb.input_keyevent(serial, 67)
        _sleep_pause(app, 0.05)

def _input_text(app, serial, text: str):
    """输入文本"""
    app.adb.input_text(serial, str(text))

def _match_in_region(png_bytes, img_path, region, threshold):
    """在指定区域内匹配图片"""
    try:
        import cv2
        import numpy as np

        # 解码图片
        screen_arr = np.frombuffer(png_bytes, dtype=np.uint8)
        scr = cv2.imdecode(screen_arr, cv2.IMREAD_COLOR)
        if scr is None:
            return False, (0, 0)

        # 裁剪区域
        (x1, y1), (x2, y2) = region
        h, w = scr.shape[:2]
        x1 = max(0, min(x1, w))
        y1 = max(0, min(y1, h))
        x2 = max(0, min(x2, w))
        y2 = max(0, min(y2, h))

        if x2 <= x1 or y2 <= y1:
            return False, (0, 0)

        cropped = scr[y1:y2, x1:x2]

        # 编码为PNG
        _, cropped_png = cv2.imencode('.png', cropped)
        cropped_bytes = cropped_png.tobytes()

        # 在裁剪区域内匹配
        ok, (rx, ry) = matcher.match_one(cropped_bytes, img_path, threshold=threshold)

        if ok:
            # 转换回原图坐标
            return True, (x1 + rx, y1 + ry)
        return False, (0, 0)
    except Exception:
        return False, (0, 0)

def _click_if_found_in_region(app, serial, png_bytes, img_path, region, threshold, log, double=False):
    """在区域内查找并点击"""
    ok, (x, y) = _match_in_region(png_bytes, img_path, region, threshold)
    if ok:
        if double:
            _double_tap(app, serial, x, y)
            log(f"[CITY] 双击 {os.path.basename(img_path)} @ ({x},{y})")
        else:
            _tap(app, serial, x, y)
            log(f"[CITY] 单击 {os.path.basename(img_path)} @ ({x},{y})")
        return True
    else:
        # 如果未找到，尝试降低置信度重新匹配
        lower_threshold = max(0.7, threshold - 0.15)
        ok, (x, y) = _match_in_region(png_bytes, img_path, region, lower_threshold)
        if ok:
            log(f"[CITY] 使用降低的置信度({lower_threshold})找到 {os.path.basename(img_path)} @ ({x},{y})")
            if double:
                _double_tap(app, serial, x, y)
            else:
                _tap(app, serial, x, y)
            return True
        log(f"[CITY] 未找到 {os.path.basename(img_path)}，检测区域: {region}，置信度: {threshold}")
    return False


def _wait_for_soldier_entry(app, serial, paths, threshold, log, should_stop,
                           max_wait: float = 8.0, initial_delay: float = 0.3, max_delay: float = 2.0):
    """
    方案C：指数退避等待 + 条件退出（检测到伤兵入口才进入治疗）
    - 每轮：截图 -> 在 SOLDIER_REGION 内匹配任一伤兵图标
    - 未命中：按 initial_delay * 2^k 退避，delay 上限 max_delay
    - 超时：返回 False，避免在错误界面“盲点”点击 (soldier_x, soldier_y)
    """
    start = time.time()
    delay = max(0.05, float(initial_delay))
    hard_cap = float(max_wait)
    # 伤兵入口识别阈值：适当放宽，避免过严导致长时间等不到
    soldier_thr = max(0.85, float(threshold) - 0.05)

    attempt = 0
    while (time.time() - start) < hard_cap:
        if should_stop():
            return False

        attempt += 1
        png = _screencap(app, serial)
        if png is None:
            log(f"[CITY] 出征后等待：第{attempt}次截图失败，退避{delay:.2f}s")
        else:
            for img_path in paths["soldiers"]:
                ok, (x, y) = _match_in_region(png, img_path, SOLDIER_REGION, soldier_thr)
                if ok:
                    log(f"[CITY] 出征后等待：检测到伤兵入口 {os.path.basename(img_path)} @ ({x},{y})，进入治疗")
                    return True
            log(f"[CITY] 出征后等待：未检测到伤兵入口（第{attempt}次），退避{delay:.2f}s")

        remaining = hard_cap - (time.time() - start)
        if remaining <= 0:
            break
        _sleep_pause(app, min(delay, remaining))
        delay = min(float(max_delay), delay * 2.0)

    log(f"[CITY] 出征后等待：超时{hard_cap:.1f}s仍未检测到伤兵入口，放弃本轮治疗以避免误触")
    return False

def _check_current_interface(app, serial, target, paths, threshold, log):
    """
    2.1.1 检测当前界面
    在指定区域内检测目标图片
    """
    png = _screencap(app, serial)
    if png is None:
        log("[CITY] 截图失败")
        return False
    
    target_img = paths["targets"][target]
    ok, (x, y) = _match_in_region(png, target_img, DETECT_REGION, threshold)
    
    target_name = TARGET_NAMES[target]
    if ok:
        log(f"[CITY] 检测到{target_name}界面 @ ({x},{y})")
        return True
    else:
        log(f"[CITY] 未检测到{target_name}界面")
        return False

def _navigate_to_target(app, serial, target, paths, threshold, log, should_stop):
    """
    2.1.2 导航到目标
    判断是否在野外，点击收藏，输入坐标
    """
    if should_stop():
        return False
    
    png = _screencap(app, serial)
    if png is None:
        log("[CITY] 截图失败")
        return False
    
    # 查找收藏图标
    ok, (x, y) = matcher.match_one(png, paths["shoucang"], threshold=threshold)
    if not ok:
        log("[CITY] 未找到收藏图标，不在野外")
        return False
    
    log("[CITY] 找到收藏图标，开始导航")
    
    # 点击收藏
    _tap(app, serial, 350, 1059)
    _sleep_pause(app, 0.5)
    
    # 点击坐标输入框
    _tap(app, serial, 239, 621)
    _sleep_pause(app, 0.3)
    
    # 输入X坐标
    _send_delete(app, serial, 4)
    _sleep_pause(app, 0.2)
    x_coord, y_coord = TARGET_COORDS[target]
    _input_text(app, serial, str(x_coord))
    _sleep_pause(app, 0.3)
    
    # 点击Y坐标输入框
    _tap(app, serial, 517, 619)
    _sleep_pause(app, 0.3)
    
    # 输入Y坐标
    _send_delete(app, serial, 4)
    _sleep_pause(app, 0.2)
    _input_text(app, serial, str(y_coord))
    _sleep_pause(app, 0.3)
    
    # 点击确认
    _tap(app, serial, 350, 751)
    _sleep_pause(app, 1.0)
    
    log(f"[CITY] 已导航到坐标 ({x_coord},{y_coord})")
    return True

def _ensure_at_target(app, serial, target, paths, threshold, log, should_stop):
    """
    确保当前在目标界面
    2.1.1 → 2.1.2 → 2.1.3 → 2.1.1
    """
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        if should_stop():
            return False
        
        log(f"[CITY] 尝试定位目标界面 ({attempt}/{max_attempts})")
        
        # 2.1.1 检测当前界面
        if _check_current_interface(app, serial, target, paths, threshold, log):
            return True
        
        # 2.1.2 尝试从野外导航
        if _navigate_to_target(app, serial, target, paths, threshold, log, should_stop):
            _sleep_pause(app, 1.0)
            # 再次检测
            if _check_current_interface(app, serial, target, paths, threshold, log):
                return True
        
        # 2.1.3 调用回到野外
        log("[CITY] 调用回到野外")
        def _noop(_): pass
        run_init_to_wild(app, serial, toast=_noop, log=log, threshold=threshold, verbose=False)
        _sleep_pause(app, 1.0)
    
    log("[CITY] 无法定位到目标界面")
    return False

def _attack_expedition(app, serial, paths, threshold, log, should_stop, queue_mode, team_toggle_state):
    """
    2.2 出征
    """
    if should_stop():
        return False, team_toggle_state
    
    log("[CITY] 开始出征流程")
    
    # 2.2.1 点击中心坐标1，然后点击红按钮
    if should_stop():
        return False, team_toggle_state

    cx, cy = ATTACK_CENTER_COORDS[0]  # 只点击第一个坐标
    log(f"[CITY] 点击中心坐标 ({cx},{cy})")
    _tap(app, serial, cx, cy)
    _sleep_pause(app, 0.3)  # 等待300ms

    # 双击出征按钮（固定坐标）
    log("[CITY] 双击出征按钮 @ (250,1100)")
    _double_tap(app, serial, 250, 1100)
    _sleep_pause(app, 0.3)  # 等待300ms
    
    # 2.2.2 选队伍
    if queue_mode == "team12":
        # 1队+2队模式，交替点击
        team_idx = team_toggle_state[0]  # 0 或 1
        tx, ty = TEAM_COORDS[team_idx]
        log(f"[CITY] 点击队伍{team_idx+1} @ ({tx},{ty})")
        _tap(app, serial, tx, ty)
        _sleep_pause(app, 0.3)
        # 切换下次使用的队伍
        team_toggle_state[0] = 1 - team_idx
    else:
        log("[CITY] 使用默认队列")
    
    # 2.2.3 出征 - 查找并点击蓝按钮
    log("[CITY] 开始查找蓝按钮...")
    png = _screencap(app, serial)
    if png is None:
        log("[CITY] 截图失败")
        return False, team_toggle_state

    log(f"[CITY] 在区域 {BLUE_BUTTON_REGION} 内查找蓝按钮，置信度: {threshold}")
    if _click_if_found_in_region(app, serial, png, paths["blue2"], BLUE_BUTTON_REGION, threshold, log, double=False):
        _sleep_pause(app, 0.5)
        log("[CITY] 出征成功")
        return True, team_toggle_state
    else:
        log("[CITY] 未找到蓝按钮，返回重新定位")
        return False, team_toggle_state

def _heal_soldiers(app, serial, paths, threshold, heal_seconds, wait_seconds, log, should_stop, soldier_x, soldier_y):
    """
    2.3 治疗
    """
    if should_stop():
        return

    log("[CITY] 开始治疗流程")

    # 2.3.1 双击治疗图标（动态坐标）
    log(f"[CITY] 双击治疗图标 @ ({soldier_x},{soldier_y})")
    _double_tap(app, serial, soldier_x, soldier_y)
    _sleep_pause(app, 0.5)
    
    # 连续点击治疗按钮
    log(f"[CITY] 连续点击治疗按钮，时长 {heal_seconds} 秒（{CLICK_RATE}次/秒）")
    end_time = time.time() + heal_seconds
    click_count = 0
    while time.time() < end_time:
        if should_stop():
            log("[CITY] 收到停止指令，中断治疗")
            break
        _tap(app, serial, *HEAL_BUTTON)
        click_count += 1
        _sleep_pause(app, CLICK_INTERVAL)
    
    log(f"[CITY] 治疗完成，共点击 {click_count} 次")
    
    # 等待时长
    if wait_seconds > 0:
        log(f"[CITY] 等待 {wait_seconds} 秒")
        _sleep_pause(app, wait_seconds)
    
    # 2.3.2 发送返回键
    log("[CITY] 发送返回键")
    _send_back(app, serial)
    _sleep_pause(app, 0.5)

def run_sweep_city(app, serial: str, target: str, queue_mode: str,
                   heal_seconds: int, wait_seconds: int, loop_interval: int,
                   toast, log, should_stop=None, threshold: float | None = None,
                   verbose: bool = False, soldier_x: int = 556, soldier_y: int = 1044):
    """
    刷王城主流程

    参数:
        target: 目标 ("north", "west", "south", "east", "sun")
        queue_mode: 队列模式 ("default", "team12")
        heal_seconds: 治疗时长（秒）
        wait_seconds: 治疗后等待时长（秒）
        loop_interval: 循环间隔（秒）
        soldier_x: 伤兵图标X坐标（默认556）
        soldier_y: 伤兵图标Y坐标（默认1044）
    """
    if should_stop is None:
        should_stop = lambda: False

    thr = 0.94 if threshold is None else float(threshold)  # 置信度要求0.94
    paths = _paths()
    target_name = TARGET_NAMES.get(target, target)

    log(f"[CITY] 开始刷王城任务")
    log(f"[CITY] 目标：{target_name}")
    log(f"[CITY] 队列模式：{'1队+2队' if queue_mode == 'team12' else '默认队列'}")
    log(f"[CITY] 治疗时长：{heal_seconds}秒，等待时长：{wait_seconds}秒，循环间隔：{loop_interval}秒")
    log(f"[CITY] 伤兵坐标：({soldier_x},{soldier_y})")
    
    # 队伍切换状态（用于1队+2队模式）
    team_toggle_state = [0]  # 0=1队, 1=2队
    
    loop_count = 0
    while not should_stop():
        loop_count += 1
        log(f"[CITY] ========== 循环 {loop_count} 开始 ==========")
        
        # 2.1 确保在目标界面
        if not _ensure_at_target(app, serial, target, paths, thr, log, should_stop):
            log("[CITY] 无法到达目标界面，等待后重试")
            _sleep_pause(app, 5.0)
            continue
        
        # 2.2 出征
        success, team_toggle_state = _attack_expedition(app, serial, paths, thr, log, should_stop, queue_mode, team_toggle_state)
        if not success:
            log("[CITY] 出征失败，发送返回键")
            _send_back(app, serial)
            _sleep_pause(app, 0.5)
            log("[CITY] 重新开始循环")
            continue
        
        # 2.3 治疗（方案C：指数退避等待 + 条件退出）
        if not _wait_for_soldier_entry(app, serial, paths, thr, log, should_stop,
                                       max_wait=8.0, initial_delay=0.3, max_delay=2.0):
            log("[CITY] 出征后界面未就绪或未出现伤兵入口：发送返回键并进入下一轮")
            _send_back(app, serial)
            _sleep_pause(app, 0.5)
            continue

        _heal_soldiers(app, serial, paths, thr, heal_seconds, wait_seconds, log, should_stop, soldier_x, soldier_y)
        
        log(f"[CITY] ========== 循环 {loop_count} 结束 ==========")
        
        # 循环间隔
        if loop_interval > 0 and not should_stop():
            log(f"[CITY] 循环间隔等待 {loop_interval} 秒")
            _sleep_pause(app, loop_interval)
    
    log("[CITY] 刷王城任务结束")

def _double_tap(app, serial, x, y, interval=0.12, post_delay=0.15):
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, interval)
    app.adb.input_tap(serial, x, y)
    _sleep_pause(app, post_delay)
