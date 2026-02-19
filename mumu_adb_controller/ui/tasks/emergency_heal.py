import time
from typing import Sequence

from ..helpers import matcher
from ...common.pathutil import res_path


THRESH = matcher.THRESH
TAP_POINT = (581, 928)
CHECK_DELAY = 0.05


def _paths():
    P = lambda n: res_path("pic", n)
    return {
        "shoucang": P("shoucang.png"),
        "daiban": P("daiban.png"),
        "xingjun": P("xingjun.png"),
        "tool_boost": P("tool_boost.png"),
        "sb_list": [P("shangbing_1.png"), P("shangbing_2.png"), P("shangbing_3.png")],
    }


def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _exist_all(png, paths, keys: Sequence[str], thr):
    return matcher.exist_all(png, paths, keys, threshold=thr)


def _double_tap(app, serial, x, y, internal_delay=0.12):
    app.adb.input_tap(serial, int(x), int(y))
    time.sleep(internal_delay)
    app.adb.input_tap(serial, int(x), int(y))


def _double_tap_any(app, serial, png, images, thr):
    for img in images:
        ok, pos = matcher.match_one(png, img, threshold=thr)
        if ok:
            _double_tap(app, serial, *pos)
            return True, img
    return False, ""


def run_emergency_heal(app, serial: str, toast, log, should_stop,
                       threshold: float | None = None, verbose: bool = False):
    """紧急治疗：返回野外 -> 打开任意伤兵 -> 连续治疗"""
    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    for img in ["shangbing_1.png", "shangbing_2.png", "shangbing_3.png", "tool_boost.png"]:
        if not os.path.isfile(res_path("pic", img)):
            toast(f"缺少模板：{res_path('pic', img)}")
            return

    log("[HEAL] 第一步：确认处于野外")
    from .init_to_wild import run_init_to_wild

    for attempt in range(1, 4):
        if should_stop():
            log("[HEAL] 收到停止指令，终止初始化流程")
            return
        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，终止任务")
            return
        if _exist_all(png, paths, ["shoucang", "daiban", "xingjun"], thr):
            log("[HEAL] 已确认在野外")
            break
        log(f"[HEAL] 不在野外，尝试第 {attempt}/3 次初始化到野外")
        run_init_to_wild(app, serial, toast=lambda *_, **__: None, log=log, threshold=thr, verbose=verbose)
        time.sleep(3.0)
    else:
        toast("三次尝试仍未回到野外，紧急治疗终止")
        return

    if should_stop():
        log("[HEAL] 收到停止指令，终止任务")
        return

    png = _screencap(app, serial)
    if png is None:
        toast("无法截图，终止任务")
        return

    log("[HEAL] 第二步：尝试打开任意伤兵条目 (shangbing_1/2/3)")
    ok, hit_img = _double_tap_any(app, serial, png, paths["sb_list"], thr)
    if not ok:
        toast("未找到任何伤兵条目，紧急治疗终止")
        return
    # 获取双击的坐标并记录
    for img in paths["sb_list"]:
        ok, pos = matcher.match_one(png, img, threshold=thr)
        if ok:
            log(f"[HEAL] 已双击打开：{os.path.basename(hit_img)}，坐标：({int(pos[0])}, {int(pos[1])})")
            break

    time.sleep(0.2)

    log("[HEAL] 第三步：连续快速点击治疗按钮，坐标：(581, 928)，每秒12次；每3秒检查一次是否继续…")
    click_count = 0
    last_check = time.time()
    while True:
        if should_stop():
            log("[HEAL] 收到停止指令，结束治疗连击")
            break
        # 连续点击（约12次/秒）
        app.adb.input_tap(serial, *TAP_POINT)
        click_count += 1
        time.sleep(1.0 / 12.0)
        # 每3秒检查一次是否继续
        if time.time() - last_check >= 3.0:
            png = _screencap(app, serial)
            if png is None:
                log("[HEAL] 截图失败，结束治疗连击")
                break
            has_tool = matcher.exist(png, paths["tool_boost"], threshold=thr)
            sb_exists = [matcher.exist(png, img, threshold=thr) for img in paths["sb_list"]]
            # 停止条件：四个图标均不存在（tool_boost 与 3个上兵）
            if (not has_tool) and (not any(sb_exists)):
                log("[HEAL] 检测到 tool_boost 与 伤兵图标均不存在，结束治疗连击")
                break
            if verbose:
                log(f"[HEAL] 继续治疗中… 当前点击 {click_count} 次")
            last_check = time.time()

    log(f"[HEAL] 紧急治疗结束，共点击 {click_count} 次")
