# mumu_adb_controller/ui/tasks/auto_like.py
import os
import sys
import time
import random
from typing import Tuple

from ..helpers import matcher

# 冻结安全的资源定位
try:
    from ...common.pathutil import res_path
except Exception:
    def _app_base_dir():
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    def res_path(*parts: str):
        return os.path.join(_app_base_dir(), *parts)

THRESH = matcher.THRESH

# 全局速度 + 全局暂停感知 sleep（不依赖 should_stop）
def _sleep(app, sec: float):
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


def _paths():
    P = lambda n: res_path("pic", n)
    return {
        # 野外三要素
        "shoucang": P("shoucang.png"),
        "daiban": P("daiban.png"),
        "xingjun": P("xingjun.png"),
        # 联盟与帮助
        "alliance": P("alliance.png"),
        "alliance_help": P("alliance_help.png"),
        "all_help": P("all_help.png"),
        "today_alliance": P("today_alliance.png"),
        # 掉线检测
        "diaoxian": P("diaoxian.png"),
    }


def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _match_one(png, path, thr):
    return matcher.match_one(png, path, threshold=thr)


def _exist(png, path, thr):
    return matcher.exist(png, path, threshold=thr)

# ROI 检测 all_help：在 (89,1020)-(602,1242) 范围内匹配，减少整屏匹配开销
# 若裁剪失败则回退为整屏检测
def _exist_all_help_roi(png, path, thr) -> bool:
    try:
        import cv2 as cv
        import numpy as np
        arr = np.frombuffer(png, dtype=np.uint8)
        img = cv.imdecode(arr, cv.IMREAD_COLOR)
        if img is None:
            return matcher.exist(png, path, threshold=thr)
        x1, y1, x2, y2 = 89, 1020, 602, 1242
        h, w = img.shape[:2]
        x1 = max(0, min(w, x1)); x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1)); y2 = max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            return matcher.exist(png, path, threshold=thr)
        roi = img[y1:y2, x1:x2]
        ok, buf = cv.imencode('.png', roi)
        if not ok:
            return matcher.exist(png, path, threshold=thr)
        return matcher.exist(buf.tobytes(), path, threshold=thr)
    except Exception:
        return matcher.exist(png, path, threshold=thr)


def _tap(app, serial, x, y):
    app.adb.input_tap(serial, int(x), int(y))


# 重新进入联盟帮助面板（自恢复）：alliance -> 1s -> alliance_help
def _reenter_alliance_help(app, serial, log, paths, thr) -> bool:
    log("[LIKE] 自恢复：尝试重新进入联盟帮助面板…")
    png = _screencap(app, serial)
    if png is None:
        log("[LIKE] 自恢复：截图失败，放弃本次重入")
        return False
    ok, pos = _match_one(png, paths["alliance"], thr)
    if not ok:
        log("[LIKE] 自恢复：未找到 alliance.png")
        return False
    _tap(app, serial, *pos)
    _sleep(app, 1.5)  # 原 1.0 → 现 1.5（受全局速度调节影响）
    png = _screencap(app, serial)
    if png is None:
        log("[LIKE] 自恢复：截图失败（alliance后）")
        return False
    ok, pos = _match_one(png, paths["alliance_help"], thr)
    if not ok:
        log("[LIKE] 自恢复：未找到 alliance_help.png")
        return False
    _tap(app, serial, *pos)
    log("[LIKE] 自恢复：已尝试打开联盟帮助面板")
    return True


def _in_wild(png, paths, thr) -> bool:
    return matcher.exist_all(png, paths, ["shoucang", "daiban", "xingjun"], threshold=thr)


def run_auto_like(app, serial: str, toast, log, should_stop,
                  threshold: float | None = None, verbose: bool = False):
    """自动点赞流程
    1) 回到野外（最多3次重试，每次等待3s）
    2) 点击 alliance.png → 等1s → 点击 alliance_help.png
    3) 每0.5s检测一次 all_help.png；检测到后在区域(258,1190)-(439,1219)内随机点击20s，速率8-12次/秒
    受阻统一先检查 diaoxian.png，存在则停止提示
    """
    # 日志前缀统一为 [HELP]
    try:
        _orig_log = log
        def _wrap(msg):
            try:
                _orig_log(str(msg).replace("[LIKE]", "[HELP]"))
            except Exception:
                pass
        log = _wrap  # 覆盖本地 log 引用
    except Exception:
        pass

    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    # 资源检查
    required = ["alliance", "alliance_help", "all_help", "today_alliance", "shoucang", "daiban", "xingjun", "diaoxian"]
    for k in required:
        if not os.path.isfile(paths[k]):
            toast(f"缺少模板：{paths[k]}")
            return

    # 第一步：回到野外
    log("[LIKE] 第一步：回到野外（初始化到野外）")
    from .init_to_wild import run_init_to_wild
    for attempt in range(1, 4):
        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，终止")
            return
        if _in_wild(png, paths, thr):
            log("[LIKE] 已在野外")
            break
        log(f"[LIKE] 不在野外 → 调用初始化到野外（第{attempt}/3次）")
        run_init_to_wild(app, serial, toast=lambda *_: None, log=log, threshold=thr, verbose=verbose)
        _sleep(app, 3.0)
        png = _screencap(app, serial)
        if png is not None and _in_wild(png, paths, thr):
            log("[LIKE] 已返回野外")
            break
        if attempt == 3:
            toast("三次尝试仍未回到野外，终止")
            return

    # 第二步：进入联盟帮助
    png = _screencap(app, serial)
    if png is None:
        toast("无法截图，终止")
        return
    ok, pos = _match_one(png, paths["alliance"], thr)
    if not ok:
        if _exist(png, paths["diaoxian"], thr):
            toast("检测到掉线，需手动处理")
            return
        toast("未找到联盟按钮")
        return
    _tap(app, serial, *pos)
    _sleep(app, 1.5)  # 原 1.0 → 现 1.5（受全局速度调节影响）
    png = _screencap(app, serial)
    if png is None:
        toast("无法截图，终止")
        return
    ok, pos = _match_one(png, paths["alliance_help"], thr)
    if not ok:
        if _exist(png, paths["diaoxian"], thr):
            toast("检测到掉线，需手动处理")
            return
        toast("未找到联盟帮助入口")
        return
    _tap(app, serial, *pos)

    # 第三步：循环等待 all_help 出现，然后连击 3 秒；完成后继续循环第三步
    log("[LIKE] 进入主循环：持续检测 all_help 面板")
    cycle_count = 0
    while True:
        cycle_count += 1
        log(f"[LIKE] 主循环第 {cycle_count} 轮开始，检查停止状态...")
        if should_stop():
            log("[LIKE] ✗ 收到停止指令，退出主循环")
            return
        else:
            log("[LIKE] ✓ 停止状态检查通过，继续执行")
        
        log(f"[LIKE] 第 {cycle_count} 轮循环开始：等待 all_help 面板出现…")
        # 等待出现 all_help，0.5s 一次；直到出现或停止
        poll_count = 0
        start_wait = time.time()
        last_recovery_check = time.time()
        found_all_help = False
        
        while not found_all_help:
            log(f"[LIKE] 检测循环第 {poll_count + 1} 次迭代，检查停止状态...")
            if should_stop():
                log("[LIKE] ✗ 收到停止指令，退出检测循环")
                return
            else:
                log("[LIKE] ✓ 检测循环停止状态检查通过")
            
            _sleep(app, 0.5)
            log("[LIKE] 开始截图...")
            png = _screencap(app, serial)
            if png is None:
                log("[LIKE] ✗ 截图失败，重试中…")
                continue
            else:
                log("[LIKE] ✓ 截图成功")
            
            # 检测 all_help（限制在 ROI 以降低资源消耗）
            log("[LIKE] 检测 all_help.png（ROI 89,1020)-(602,1242）...")
            if _exist_all_help_roi(png, paths["all_help"], thr):
                elapsed = time.time() - start_wait
                log(f"[LIKE] ✓ 检测到 all_help（ROI），等待用时 {elapsed:.1f}s")
                found_all_help = True
                break
            else:
                log("[LIKE] 未检测到 all_help.png（ROI）")

            # 掉线检测
            log("[LIKE] 检测掉线状态...")
            if _exist(png, paths["diaoxian"], thr):
                toast("检测到掉线，需手动处理")
                log("[LIKE] ✗ 检测到掉线，终止流程")
                return
            else:
                log("[LIKE] ✓ 掉线检测通过")
            
            # 自恢复：每隔 1 分钟检查 today_alliance 是否存在；若不存在则重进帮助面板
            current_time = time.time()
            if current_time - last_recovery_check >= 60.0:
                log("[LIKE] 执行自恢复检查...")
                last_recovery_check = current_time
                if not _exist(png, paths["today_alliance"], thr):
                    log("[LIKE] 自恢复：未检测到 today_alliance.png，尝试重新进入帮助面板…")
                    if _reenter_alliance_help(app, serial, log, paths, thr):
                        # 重置等待计时与计数
                        start_wait = time.time()
                        poll_count = 0
                        log("[LIKE] 自恢复成功，重置等待计时器")
                        continue
                    else:
                        log("[LIKE] 自恢复失败，继续轮询…")
                else:
                    log("[LIKE] ✓ today_alliance.png 存在，无需自恢复")
            else:
                log(f"[LIKE] 自恢复检查倒计时: {60.0 - (current_time - last_recovery_check):.1f}s")
            
            poll_count += 1
            # 每 2 秒输出一次进度
            if (poll_count % 4 == 0):
                elapsed = time.time() - start_wait
                log(f"[LIKE] 第 {cycle_count} 轮 - 未检测到 all_help，已等待 {elapsed:.1f}s，轮询次数 {poll_count}（持续轮询中）")
            else:
                log(f"[LIKE] 第 {cycle_count} 轮 - 轮询次数 {poll_count}，等待中...")
        
        # 检测到 all_help → 连击 3 秒
        if found_all_help:
            log("[LIKE] 开始随机连击 300 秒（8-16 次/秒）…")
            clicks = 0
            end_t = time.time() + 300.0
            while time.time() < end_t:
                log(f"[LIKE] 连击循环，剩余时间: {end_t - time.time():.1f}s")
                if should_stop():
                    log("[LIKE] ✗ 收到停止指令，退出连击")
                    return
                x = random.randint(258, 439)
                y = random.randint(1190, 1219)
                log(f"[LIKE] 点击坐标: ({x}, {y})")
                _tap(app, serial, x, y)
                clicks += 1
                # 8-16 次/秒 → 每次间隔大约 1/8 到 1/16 秒
                interval = 1.0 / random.randint(8, 16)
                log(f"[LIKE] 点击 {clicks} 次，等待 {interval:.2f}s")
                _sleep(app, interval)
            log(f"[LIKE] 第 {cycle_count} 轮连击结束，共点击 {clicks} 次；准备下一轮检测…")
            _sleep(app, 0.5)  # 短暂间隔后继续检测
        else:
            log("[LIKE] ✗ 未找到 all_help，但循环退出，可能有问题")

