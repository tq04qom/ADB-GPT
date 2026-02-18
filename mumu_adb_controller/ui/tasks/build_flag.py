import os
import sys
import time
from typing import Callable

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


def _sleep(app, sec: float):
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
        "lianmengqizhi": P("lianmengqizhi.png"),
        "build": P("build.png"),
        "paiqianbudui": P("paiqianbudui.png"),
        "pohuai": P("pohuai.png"),
        "chuzheng_big": P("chuzheng_big.png"),
    }


def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


# 直接点击（不强制最小间隔）
def _tap(app, serial, x, y):
    app.adb.input_tap(serial, int(x), int(y))


def _exist_roi(png, path, thr, x1, y1, x2, y2) -> bool:
    try:
        import cv2 as cv
        import numpy as np
        arr = np.frombuffer(png, dtype=np.uint8)
        img = cv.imdecode(arr, cv.IMREAD_COLOR)
        if img is None:
            return matcher.exist(png, path, threshold=thr)
        h, w = img.shape[:2]
        x1c, x2c = max(0, min(w, x1)), max(0, min(w, x2))
        y1c, y2c = max(0, min(h, y1)), max(0, min(h, y2))
        if x2c <= x1c or y2c <= y1c:
            return matcher.exist(png, path, threshold=thr)
        roi = img[y1c:y2c, x1c:x2c]
        ok, buf = cv.imencode('.png', roi)
        if not ok:
            return matcher.exist(png, path, threshold=thr)
        return matcher.exist(buf.tobytes(), path, threshold=thr)
    except Exception:
        return matcher.exist(png, path, threshold=thr)


def _match_one_roi(png, path, thr, x1, y1, x2, y2):
    """在指定 ROI 内进行 match_one，返回 (ok, (x,y))，x,y 是相对于整张图的坐标。"""
    try:
        import cv2 as cv
        import numpy as np
        arr = np.frombuffer(png, dtype=np.uint8)
        img = cv.imdecode(arr, cv.IMREAD_COLOR)
        if img is None:
            return matcher.match_one(png, path, threshold=thr)
        h, w = img.shape[:2]
        x1c, x2c = max(0, min(w, x1)), max(0, min(w, x2))
        y1c, y2c = max(0, min(h, y1)), max(0, min(h, y2))
        if x2c <= x1c or y2c <= y1c:
            return matcher.match_one(png, path, threshold=thr)
        roi = img[y1c:y2c, x1c:x2c]
        ok, buf = cv.imencode('.png', roi)
        if not ok:
            return matcher.match_one(png, path, threshold=thr)
        okm, pos = matcher.match_one(buf.tobytes(), path, threshold=thr)
        if not okm:
            return False, (0, 0)
        # pos is relative to ROI; map to full image coords
        rx, ry = pos
        return True, (int(rx + x1c), int(ry + y1c))
    except Exception:
        return matcher.match_one(png, path, threshold=thr)


def run_build_flag(app, serial: str, toast: Callable, log: Callable,
                   should_stop: Callable[[], bool],
                   threshold: float | None = None, verbose: bool = False):
    """循环执行建旗子流程，每 60 秒执行一次，直到 should_stop() 返回 True

    按用户描述的步骤实现，如缺少模板会提前提示并退出。
    """
    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    for k, p in paths.items():
        if not os.path.isfile(p):
            toast(f"缺少模板：{p}")
            return

    from .init_to_wild import run_init_to_wild

    cycle = 0
    while True:
        cycle += 1
        log(f"[BUILD_FLAG] 第 {cycle} 轮开始，检查停止状态...")
        if should_stop():
            log("[BUILD_FLAG] 收到停止指令，退出")
            return

        # 初始化到野外
        log("[BUILD_FLAG] 调用初始化到野外")
        run_init_to_wild(app, serial, toast=lambda *_: None, log=log, threshold=thr, verbose=verbose)
        # 等待 1s
        _sleep(app, 1.0)

        # 前置点击序列：点击 (343,1139) 等待2s，再点击 (359,115) 等待2s
        _tap(app, serial, 343, 1139)
        _sleep(app, 2.0)
        _tap(app, serial, 359, 115)
        _sleep(app, 2.0)

        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，跳过本轮")
            # 等待下一轮
            for _ in range(60):
                if should_stop():
                    log("[BUILD_FLAG] 收到停止指令，退出等待")
                    return
                _sleep(app, 1.0)
            continue

        # 在 ROI (133,970)-(582,1131) 检测 lianmengqizhi（直接裁剪 ROI 后匹配）
        roi_x1, roi_y1, roi_x2, roi_y2 = 133, 970, 582, 1131
        ok, pos = _match_one_roi(png, paths["lianmengqizhi"], thr, roi_x1, roi_y1, roi_x2, roi_y2)
        if ok:
            log("[BUILD_FLAG] 在 ROI 内匹配到 lianmengqizhi，尝试点击")
            _tap(app, serial, *pos)
            # 点击 lianmengqizhi 后等待 3s
            _sleep(app, 3.0)
            _tap(app, serial, 357, 632)
            # 点击坐标 (357,632) 后等待 1s
            _sleep(app, 1.0)

            png2 = _screencap(app, serial)
            if png2 is None:
                log("[BUILD_FLAG] 点击后截图失败")
            else:
                okb, posb = matcher.match_one(png2, paths["build"], threshold=thr)
                if okb:
                    log("[BUILD_FLAG] 检测到 build.png，点击并尝试排遣队伍")
                    _tap(app, serial, *posb)
                    _sleep(app, 1.0)
                    # 重新截图检测 paiqianbudui
                    png_after_build = _screencap(app, serial)
                    if png_after_build is None:
                        log("[BUILD_FLAG] build 后截图失败")
                    else:
                        okp, posp = matcher.match_one(png_after_build, paths["paiqianbudui"], threshold=thr)
                        if okp:
                            _tap(app, serial, *posp)
                            _sleep(app, 1.0)
                            # 点击 paiqianbudui 后再检测并点击 chuzheng_big
                            png_after_pai = _screencap(app, serial)
                            if png_after_pai:
                                okc, posc = matcher.match_one(png_after_pai, paths["chuzheng_big"], threshold=thr)
                                if okc:
                                    _tap(app, serial, *posc)
                                    _sleep(app, 0.5)
                                else:
                                    log("[BUILD_FLAG] 未找到 chuzheng_big.png（paiqian后）")
                        else:
                            log("[BUILD_FLAG] 未检测到 paiqianbudui.png（build后）")
                else:
                    log("[BUILD_FLAG] 未检测到 build.png，尝试点击 pohuai.png")
                    okph, posph = matcher.match_one(png2, paths["pohuai"], threshold=thr)
                    if okph:
                        _tap(app, serial, *posph)
                        _sleep(app, 1.0)
                        # 点击 pohuai 后检测并点击 chuzheng_big
                        png_after_ph = _screencap(app, serial)
                        if png_after_ph:
                            okc2, posc2 = matcher.match_one(png_after_ph, paths["chuzheng_big"], threshold=thr)
                            if okc2:
                                _tap(app, serial, *posc2)
                                _sleep(app, 0.5)
                            else:
                                log("[BUILD_FLAG] 未找到 chuzheng_big.png（pohuai后）")
        else:
            log("[BUILD_FLAG] 未检测到 lianmengqizhi.png，跳过相关操作")

        # （chuzheng_big 的点击由 build/pohuai 分支负责）

        # 结尾一系列操作：初始化野外，点击(304,1131)，等待2s，重复点击并输入文本，点击(615,1215)，再初始化野外
        log("[BUILD_FLAG] 结尾操作：返回并填写出征备注")
        run_init_to_wild(app, serial, toast=lambda *_: None, log=log, threshold=thr, verbose=verbose)
        _tap(app, serial, 304, 1131)
        _sleep(app, 2.0)
        # 再点击一次以打开输入框（若无影响也可安全）
        _tap(app, serial, 315, 1216)
        _sleep(app, 2.0)
        try:
            app.adb.input_text(serial, "已出征")
            _sleep(app, 0.2)
            _tap(app, serial, 615, 1215)
        except Exception:
            log("[BUILD_FLAG] 输入或点击失败（可能设备不支持输入事件）")
        run_init_to_wild(app, serial, toast=lambda *_: None, log=log, threshold=thr, verbose=verbose)

        # 等待 60s（可中断）
        for _ in range(60):
            if should_stop():
                log("[BUILD_FLAG] 收到停止指令，退出等待")
                return
            _sleep(app, 1.0)
