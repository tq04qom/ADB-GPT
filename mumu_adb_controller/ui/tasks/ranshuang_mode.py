"""
燃霜模式 - 自动打雇佣兵和升级技能
"""
import os
import sys
import time
from typing import Callable

from ..helpers import matcher

try:
    from ...common.pathutil import res_path
except Exception:
    def _app_base_dir():
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    def res_path(*parts: str):
        return os.path.join(_app_base_dir(), *parts)


def _sleep(app, sec: float):
    """带速度因子且可全局暂停的 sleep"""
    factor = 1.0
    try:
        factor = float(getattr(app, "get_speed_factor")())
    except Exception:
        try:
            factor = float(getattr(app, "speed_factor", 1.0))
        except Exception:
            factor = 1.0
    end = time.time() + max(0.0, sec * factor)
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        while pause_ev is not None and pause_ev.is_set():
            time.sleep(0.05)
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(0.1, remaining))


def _paths() -> dict:
    """返回所需图片路径"""
    P = lambda name: res_path("pic", name)
    return {
        "ranshuang_find": P("ranshuang_find.png"),
        "cancel": P("cancel.png"),
        "chengzhen": P("chengzhen.png"),
        "ranshuang": P("ranshuang.png"),
        "full_queue6": P("full_queue6.png"),
        "full_queue5": P("full_queue5.png"),
        "chuzheng_red": P("chuzheng_red.png"),
        "chuzheng_blue_2": P("chuzheng_blue_2.png"),
        "ranshuang_jineng": P("ranshuang_jineng.png"),
        "study": P("study.png"),
    }


def _screencap(app, serial: str) -> bytes | None:
    """截图"""
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _match_one(png: bytes, path: str, thr: float):
    """匹配单个图片"""
    return matcher.match_one(png, path, threshold=thr)


def _exist(png: bytes, path: str, thr: float) -> bool:
    """检查图片是否存在"""
    return matcher.exist(png, path, threshold=thr)


def _tap(app, serial: str, x: int, y: int):
    """点击坐标"""
    app.adb.input_tap(serial, int(x), int(y))


def _back(app, serial: str):
    """发送返回键"""
    app.adb.input_back(serial)


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


def _ensure_initial_state(app, serial: str, paths: dict, thr: float, log: Callable, should_stop: Callable) -> bool:
    """
    1.1 确定初始状态：查找 ranshuang_find.png
    1.2 如果找不到，每秒发送返回键并查找，连续4次未找到则点击cancel、chengzhen、ranshuang
    """
    log("[燃霜] 步骤1：确定初始状态")
    
    # 先尝试直接查找
    scr = _screencap(app, serial)
    if scr and _exist(scr, paths["ranshuang_find"], thr):
        log("[燃霜] 已在初始状态")
        return True
    
    # 循环尝试返回键
    for attempt in range(1, 5):
        if should_stop and should_stop():
            return False
        
        log(f"[燃霜] 发送返回键 ({attempt}/4)")
        _back(app, serial)
        _sleep(app, 1.0)
        
        scr = _screencap(app, serial)
        if scr and _exist(scr, paths["ranshuang_find"], thr):
            log("[燃霜] 找到初始状态")
            return True
    
    # 连续4次未找到，尝试重新进入
    log("[燃霜] 连续4次未找到，尝试重新进入燃霜界面")
    
    scr = _screencap(app, serial)
    if scr:
        # 点击cancel（如果存在）
        ok, pos = _match_one(scr, paths["cancel"], thr)
        if ok:
            log(f"[燃霜] 点击cancel @ {pos}")
            _tap(app, serial, *pos)
            _sleep(app, 0.5)
    
    # 点击chengzhen
    scr = _screencap(app, serial)
    if scr:
        ok, pos = _match_one(scr, paths["chengzhen"], thr)
        if ok:
            log(f"[燃霜] 点击chengzhen @ {pos}")
            _tap(app, serial, *pos)
            _sleep(app, 3.0)
        else:
            log("[燃霜] 未找到chengzhen")
            return False
    
    # 点击ranshuang
    scr = _screencap(app, serial)
    if scr:
        ok, pos = _match_one(scr, paths["ranshuang"], thr)
        if ok:
            log(f"[燃霜] 点击ranshuang @ {pos}")
            _tap(app, serial, *pos)
            _sleep(app, 1.0)
        else:
            log("[燃霜] 未找到ranshuang")
            return False
    
    # 再次检查是否进入初始状态
    scr = _screencap(app, serial)
    if scr and _exist(scr, paths["ranshuang_find"], thr):
        log("[燃霜] 成功进入初始状态")
        return True
    
    log("[燃霜] 无法进入初始状态")
    return False


def _check_full_queue(app, serial: str, paths: dict, log: Callable) -> bool:
    """
    2.1 判断是否满编：在(14, 146) (298, 311)范围内查找full_queue6或full_queue5（置信度0.96）
    """
    scr = _screencap(app, serial)
    if not scr:
        return False
    
    region = ((14, 146), (298, 311))
    
    # 检查full_queue6
    ok6, pos6 = _match_in_region(scr, paths["full_queue6"], region, 0.96)
    if ok6:
        log(f"[燃霜] 检测到满编状态 (full_queue6) @ {pos6}")
        return True
    
    # 检查full_queue5
    ok5, pos5 = _match_in_region(scr, paths["full_queue5"], region, 0.96)
    if ok5:
        log(f"[燃霜] 检测到满编状态 (full_queue5) @ {pos5}")
        return True
    
    log("[燃霜] 非满编状态")
    return False


def _fight_mercenary(app, serial: str, paths: dict, thr: float, log: Callable, should_stop: Callable) -> bool:
    """
    2.2 打雇佣兵：点击ranshuang_find -> 等待1s -> 点击(361, 621) -> 点击chuzheng_red -> 等待0.5s -> 点击chuzheng_blue_2
    连续5次找不到关键图片则返回False
    """
    log("[燃霜] 开始打雇佣兵")
    
    fail_count = 0
    max_fails = 5
    
    while fail_count < max_fails:
        if should_stop and should_stop():
            return False
        
        # 点击ranshuang_find
        scr = _screencap(app, serial)
        if not scr:
            fail_count += 1
            continue
        
        ok, pos = _match_one(scr, paths["ranshuang_find"], thr)
        if not ok:
            log(f"[燃霜] 未找到ranshuang_find ({fail_count + 1}/{max_fails})")
            fail_count += 1
            _sleep(app, 1.0)
            continue
        
        log(f"[燃霜] 点击ranshuang_find @ {pos}")
        _tap(app, serial, *pos)
        _sleep(app, 1.0)
        
        # 点击固定坐标(361, 621)
        log("[燃霜] 点击坐标 (361, 621)")
        _tap(app, serial, 361, 621)
        _sleep(app, 0.5)
        
        # 点击chuzheng_red
        scr = _screencap(app, serial)
        if not scr:
            fail_count += 1
            continue
        
        ok, pos = _match_one(scr, paths["chuzheng_red"], thr)
        if not ok:
            log(f"[燃霜] 未找到chuzheng_red ({fail_count + 1}/{max_fails})")
            fail_count += 1
            _sleep(app, 1.0)
            continue
        
        log(f"[燃霜] 点击chuzheng_red @ {pos}")
        _tap(app, serial, *pos)
        _sleep(app, 0.5)
        
        # 点击chuzheng_blue_2
        scr = _screencap(app, serial)
        if not scr:
            fail_count += 1
            continue
        
        ok, pos = _match_one(scr, paths["chuzheng_blue_2"], thr)
        if not ok:
            log(f"[燃霜] 未找到chuzheng_blue_2 ({fail_count + 1}/{max_fails})")
            fail_count += 1
            _sleep(app, 1.0)
            continue
        
        log(f"[燃霜] 点击chuzheng_blue_2 @ {pos}")
        _tap(app, serial, *pos)
        _sleep(app, 1.0)
        
        # 成功完成一次打雇佣兵
        return True
    
    log("[燃霜] 连续5次操作失败")
    return False


def run_ranshuang_mode(app, serial: str, toast, log, should_stop,
                       threshold: float | None = None, verbose: bool = False):
    """
    燃霜模式主流程
    """
    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()
    
    # 检查必需的模板文件
    required = ["ranshuang_find", "chengzhen", "ranshuang", "full_queue6", "full_queue5",
                "chuzheng_red", "chuzheng_blue_2", "ranshuang_jineng", "study"]
    for key in required:
        if not os.path.isfile(paths[key]):
            toast(f"缺少模板：{paths[key]}")
            log(f"[燃霜] 缺少模板：{paths[key]}")
            return
    
    log("[燃霜] ========== 开始燃霜模式 ==========")
    toast("开始燃霜模式")
    
    # 记录上次升级技能的时间
    last_skill_upgrade_time = 0
    skill_upgrade_cooldown = 180  # 3分钟 = 180秒
    
    while True:
        if should_stop and should_stop():
            log("[燃霜] 任务被停止")
            toast("燃霜模式已停止")
            break
        
        # 步骤1：确保在初始状态
        if not _ensure_initial_state(app, serial, paths, thr, log, should_stop):
            log("[燃霜] 无法进入初始状态，退出")
            toast("燃霜模式：无法进入初始状态")
            break
        
        # 步骤2：检查是否满编
        is_full = _check_full_queue(app, serial, paths, log)
        
        if not is_full:
            # 2.2 非满编状态，打雇佣兵
            if not _fight_mercenary(app, serial, paths, thr, log, should_stop):
                # 连续失败，返回步骤1
                log("[燃霜] 打雇佣兵失败，返回初始状态")
                continue
        else:
            # 2.3 满编状态，尝试升级技能
            current_time = time.time()
            if current_time - last_skill_upgrade_time >= skill_upgrade_cooldown:
                log("[燃霜] 满编状态，尝试升级技能")
                
                # 先返回初始状态
                if not _ensure_initial_state(app, serial, paths, thr, log, should_stop):
                    continue
                
                # 点击ranshuang_jineng
                scr = _screencap(app, serial)
                if scr:
                    ok, pos = _match_one(scr, paths["ranshuang_jineng"], thr)
                    if ok:
                        log(f"[燃霜] 点击ranshuang_jineng @ {pos}")
                        _tap(app, serial, *pos)
                        _sleep(app, 1.0)
                        
                        # 尝试升级5个技能
                        skill_coords = [
                            (515, 562),   # 技能1
                            (528, 710),   # 技能2
                            (174, 866),   # 技能3
                            (161, 1035),  # 技能4
                            (588, 1170),  # 技能5
                        ]
                        
                        for i, (sx, sy) in enumerate(skill_coords, 1):
                            if should_stop and should_stop():
                                break
                            
                            log(f"[燃霜] 点击技能{i} @ ({sx}, {sy})")
                            _tap(app, serial, sx, sy)
                            _sleep(app, 0.5)
                            
                            # 尝试点击study
                            scr = _screencap(app, serial)
                            if scr:
                                ok_study, pos_study = _match_one(scr, paths["study"], thr)
                                if ok_study:
                                    log(f"[燃霜] 点击study @ {pos_study}")
                                    _tap(app, serial, *pos_study)
                                    _sleep(app, 0.5)
                        
                        # 更新上次升级时间
                        last_skill_upgrade_time = current_time
                        log("[燃霜] 技能升级完成，3分钟内不再触发")
                    else:
                        log("[燃霜] 未找到ranshuang_jineng")
            else:
                remaining = skill_upgrade_cooldown - (current_time - last_skill_upgrade_time)
                log(f"[燃霜] 满编状态，技能升级冷却中（剩余{int(remaining)}秒）")
        
        # 短暂等待后继续循环
        _sleep(app, 2.0)
    
    log("[燃霜] ========== 燃霜模式结束 ==========")

