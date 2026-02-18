# mumu_adb_controller/ui/tasks/fast_join_rally.py
import os, sys, time
from typing import Callable, Optional
from ..helpers import matcher

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

P = lambda n: res_path("pic", n)

IMG_CANCEL = P("cancel.png")
IMG_DIAOXIAN = P("diaoxian.png")
IMG_HAIDAO = P("haidao.png")
IMG_WRONG = P("wrong.png")
IMG_AIM = P("aim.png")
IMG_AIM2 = P("aim2.png")

IMG_JOIN = P("join.png")
IMG_CHUZHENG_BLUE_2 = P("chuzheng_blue_2.png")

BACK_KEY_INTERVAL = 0.40  # 第一阶段：返回键间隔（秒）
STEP2_INTERVAL = 5.0      # 第二阶段：检测aim的周期
STEP3_INTERVAL = 5.0      # 第三阶段：检测join的周期
TIMEOUT_2MIN = 120.0


def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None

def _tap(app, serial, x, y):
    app.adb.input_tap(serial, int(x), int(y))

def _match_one(png_bytes, img_path, threshold=None):
    thr = matcher.THRESH if threshold is None else threshold
    return matcher.match_one(png_bytes, img_path, threshold=thr)

def _tap_if_found(app, serial, img_path, log, name: str, threshold=None):
    png = _screencap(app, serial)
    if png is None:
        log(f"[{name}] 截图失败")
        return False
    ok, (x, y) = _match_one(png, img_path, threshold=threshold)
    if ok:
        _tap(app, serial, x, y)
        log(f"[{name}] 点击 {os.path.basename(img_path)} → ({x},{y})")
        return True
    return False


def run_fast_join_rally(app, serial: str, toast: Callable[[str], None], log: Callable[[str], None],
                        should_stop: Callable[[], bool], threshold: Optional[float] = None,
                        verbose: bool = False):
    """
    新增功能：秒进集结
    流程（按你的最新规则）：
      1) 异常检测与处理：连续发送返回键直到检测到 cancel 并点击（间隔400ms，最多5次；未检测到也继续），等待400ms后进行异常图标检测（掉线/海岛/服务协议）→ 无异常进入第2步
      2) 轮询 aim.png（每5秒，≤2分钟），命中→点击并进入第3步；否则超时回到第1步
      3) 第三步（新）：等待1秒检测 join.png（阈值≥0.95）；若存在：点击 join → 1秒后点击 chuzheng_blue_2（无论是否存在）→ 再等待1秒后连续发送返回键直到检测到 cancel 并点击（间隔400ms，最多5次；若未检测到则回到第1步）；若不存在：等待2秒并执行一次向上拖动（554,1092）→（554,251），然后继续第三步；若连续2分钟未检测到 join 则回到第1步。
    """
    log("[FAST-JOIN] 启动：秒进集结")
    toast("秒进集结启动")

    def _sleep_check(seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            if should_stop():
                return True
            time.sleep(min(0.1, end - time.time()))
        return False

    skip_step1 = False
    while not should_stop():
        # ---------------- 第一步：异常状态处理 ----------------
        if skip_step1:
            # 按规则：第三步结束后直接回到第二步，本轮跳过第一步
            skip_step1 = False
        else:
            log("[STEP1] 异常检测：连续发送返回键，直至发现 cancel 并点击（最多5次）…")
            for _ in range(5):
                if should_stop():
                    return
                app.adb.input_back(serial)
                if _sleep_check(BACK_KEY_INTERVAL):
                    return
                # 每次返回后尝试点击 cancel
                if _tap_if_found(app, serial, IMG_CANCEL, log, "STEP1-cancel"):
                    break
            # 等待400ms后进行异常图标检测
            if _sleep_check(0.4):
                return

            # 截图一次做异常判断
            png = _screencap(app, serial)
            if png is None:
                log("[STEP1] 截图失败，1分钟后重试第一步")
                if _sleep_check(60.0):
                    return
                continue

        # 1) 掉线
        ok, _ = _match_one(png, IMG_DIAOXIAN, threshold=threshold)
        if ok:
            toast("检测到掉线，等待1分钟重试")
            log("[STEP1] 掉线：等待1分钟后重试第一步…")
            if _sleep_check(60.0):
                return
            continue
        # 2) 海岛
        ok, _ = _match_one(png, IMG_HAIDAO, threshold=threshold)
        if ok:
            toast("检测到海岛，尝试退出…")
            log("[STEP1] 海岛：双击(48,22) 并等待2秒")
            _tap(app, serial, 48, 22); time.sleep(0.1); _tap(app, serial, 48, 22)
            if _sleep_check(2.0):
                return
            # 重新开始第一步
            continue
        # 3) 服务协议
        ok, (xw, yw) = _match_one(png, IMG_WRONG, threshold=threshold)
        if ok:
            toast("检测到服务协议，点击关闭…")
            _tap(app, serial, xw, yw)
            if _sleep_check(0.5):
                return
            # 重新开始第一步
            continue

        # ---------------- 第二步：查找 aim 或 aim2（任一） ----------------
        log("[STEP2] 每5秒检测 pic/aim.png 或 pic/aim2.png（≤2分钟，任一命中即进入第三步）…")
        t0 = time.time()
        hit_aim = False
        while not should_stop() and (time.time() - t0) < TIMEOUT_2MIN:
            if (
                _tap_if_found(app, serial, IMG_AIM, log, "STEP2-aim", threshold=threshold)
                or _tap_if_found(app, serial, IMG_AIM2, log, "STEP2-aim2", threshold=threshold)
            ):
                hit_aim = True
                break
            if _sleep_check(STEP2_INTERVAL):
                return
        if not hit_aim:
            log("[STEP2] 2分钟未发现 aim/aim2 → 回到第一步")
            continue

        # ---------------- 第三步：查找 join（新逻辑：1秒检测；未见→2秒后拖动滚动；≤2分钟） ----------------
        log("[STEP3] 等待1秒检测 join.png（阈值0.95）；未见→等待2秒并向上拖动后重试（≤2分钟）…")
        t1 = time.time()
        found_and_back = False
        while not should_stop() and (time.time() - t1) < TIMEOUT_2MIN:
            # 等待1秒后进行检测
            if _sleep_check(1.0):
                return
            png = _screencap(app, serial)
            if png is None:
                log("[STEP3] 截图失败，继续重试…")
                continue
            ok, (xj, yj) = _match_one(png, IMG_JOIN, threshold=0.95)
            if ok:
                _tap(app, serial, xj, yj)
                log(f"[STEP3] 点击 join({xj},{yj}) → 1秒后尝试出征按钮")
                if _sleep_check(1.0):
                    return
                # 无论是否存在都尝试点击一次
                _tap_if_found(app, serial, IMG_CHUZHENG_BLUE_2, log, "STEP3-chuzheng_blue_2", threshold=threshold)
                if _sleep_check(1.0):
                    return
                # 连续发送返回键，直到检测到 cancel 并点击（最多5次）
                back_ok = False
                for _ in range(5):
                    app.adb.input_back(serial)
                    if _sleep_check(BACK_KEY_INTERVAL):
                        return
                    if _tap_if_found(app, serial, IMG_CANCEL, log, "STEP3-cancel-after-join"):
                        back_ok = True
                        break
                if not back_ok:
                    log("[STEP3] 5次返回未见 cancel → 回到第一步")
                    # 回到第一步
                    break
                # 看到 cancel 并点击后，回到第二步
                log("[STEP3] 已返回至可见 cancel 状态 → 回到第二步")
                found_and_back = True
                break
            else:
                # 未见 join：等待2秒并执行拖动滚动
                if _sleep_check(2.0):
                    return
                app.adb.input_swipe(serial, 554, 1092, 554, 251, duration=600)
                log("[STEP3] 未见 join → 已向上拖动（554,1092）→（554,251），继续重试…")
                continue
        if not found_and_back:
            # 超时或5次返回失败
            if (time.time() - t1) >= TIMEOUT_2MIN:
                log("[STEP3] 2分钟未发现 join → 回到第一步")
            # 默认回到第一步
            continue
        # 成功返回到 cancel 后，从第二步继续
        skip_step1 = True
        continue
        # 继续下一轮，从第二步开始

    toast("秒进集结已停止")
    log("[FAST-JOIN] 结束")

