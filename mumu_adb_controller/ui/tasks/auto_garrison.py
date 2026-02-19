import time
import random
from typing import Tuple

from ..helpers import matcher
from ..helpers.sleep_utils import friendly_sleep
from ...common.pathutil import res_path


THRESH = matcher.THRESH


def _sleep(app, sec: float):
    """带速度因子且可全局暂停的 sleep（不依赖 should_stop）"""
    factor = 1.0
    try:
        factor = float(getattr(app, "get_speed_factor")())
    except Exception:
        try:
            factor = float(getattr(app, "speed_factor", 1.0))
        except Exception:
            factor = 1.0
    friendly_sleep(app, sec * factor)


def _paths() -> dict:
    P = lambda name: res_path("pic", name)
    return {
        "shoucang": P("shoucang.png"),
        "daiban": P("daiban.png"),
        "xingjun": P("xingjun.png"),
        "alliance": P("alliance.png"),
        "alliance_war": P("alliance_war.png"),
        "auto_join": P("auto_join.png"),
        "stop_gray": P("stop_gray.png"),
        "stop_red": P("stop_red.png"),
        "diaoxian": P("diaoxian.png"),
        "goto": P("goto.png"),
        "ruins": P("ruins.png"),
        "zhanling": P("zhanling.png"),
        "goto_search": P("goto_search.png"),
        "chuzheng_blue_2": P("chuzheng_blue_2.png"),
    }


def _screencap(app, serial: str) -> bytes | None:
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _exist(png: bytes, path: str, thr: float) -> bool:
    return matcher.exist(png, path, threshold=thr)


def _match_one(png: bytes, path: str, thr: float):
    return matcher.match_one(png, path, threshold=thr)


def _tap(app, serial: str, x: int, y: int):
    app.adb.input_tap(serial, int(x), int(y))


def _tap_img(app, serial: str, png: bytes, path: str, thr: float, log, name: str,
             wait_s: float = 0.0) -> Tuple[bool, Tuple[int, int]]:
    ok, pos = _match_one(png, path, thr)
    log(f"[GARRISON] 点击{name}：{'命中' if ok else '未找到'} {pos if pos else ''}")
    if ok:
        _tap(app, serial, *pos)
        if wait_s > 0:
            _sleep(app, wait_s)
    return ok, (pos if pos else (-1, -1))


def _in_wild(png: bytes, paths: dict, thr: float) -> bool:
    return matcher.exist_all(png, paths, ["shoucang", "daiban", "xingjun"], threshold=thr)


def _ensure_in_wild(app, serial: str, paths: dict, thr: float, toast, log, verbose: bool) -> bool:
    log("[GARRISON] 第一步：回到野外（初始化到野外）")
    from .init_to_wild import run_init_to_wild

    for attempt in range(1, 4):
        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，已终止任务")
            return False
        if _in_wild(png, paths, thr):
            log("[GARRISON] 已在野外")
            return True

        log(f"[GARRISON] 不在野外 → 调用初始化到野外（第{attempt}/3次）")

        def _noop(_):
            pass

        run_init_to_wild(app, serial, toast=_noop, log=log, threshold=thr, verbose=verbose)
        _sleep(app, 3.0)
        png = _screencap(app, serial)
        if png is not None and _in_wild(png, paths, thr):
            log("[GARRISON] 已返回野外")
            return True

    toast("三次尝试仍未回到野外，任务结束")
    return False


# --------------------- 联盟帮助控制 ---------------------

def run_close_alliance_help(app, serial: str, toast, log,
                            threshold: float | None = None, verbose: bool = False):
    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    for key in ["alliance", "alliance_war", "auto_join", "stop_gray", "stop_red",
                "shoucang", "daiban", "xingjun", "diaoxian"]:
        if not os.path.isfile(paths[key]):
            toast(f"缺少模板：{paths[key]}")
            return

    if not _ensure_in_wild(app, serial, paths, thr, toast, log, verbose):
        return

    png = _screencap(app, serial)
    if png is None:
        toast("无法截图，已终止任务")
        return

    ok, _ = _tap_img(app, serial, png, paths["alliance"], thr, log, "pic/alliance.png", wait_s=2.0)
    if not ok:
        if _exist(png, paths["diaoxian"], thr):
            toast("检测到掉线，请手动处理")
        else:
            toast("未找到联盟按钮")
        return

    png = _screencap(app, serial)
    if png is None:
        toast("无法截图，已终止任务")
        return

    ok, _ = _tap_img(app, serial, png, paths["alliance_war"], thr, log, "pic/alliance_war.png", wait_s=1.0)
    if not ok:
        if _exist(png, paths["diaoxian"], thr):
            toast("检测到掉线，请手动处理")
        else:
            toast("未找到联盟战入口")
        return

    log("[GARRISON] 点击坐标 (355, 1212)")
    _tap(app, serial, 355, 1212)
    _sleep(app, 1.0)
    log("[GARRISON] 点击坐标 (187, 1090)")
    _tap(app, serial, 187, 1090)
    _sleep(app, 1.0)
    for i in range(3):
        app.adb.input_back(serial)
        log(f"[GARRISON] 发送第 {i+1}/3 次返回键")
        _sleep(app, 0.3)

    png = _screencap(app, serial)
    if png is None or not _in_wild(png, paths, thr):
        log("[GARRISON] 返回后未确认在野外（忽略）")
    else:
        log("[GARRISON] 已确认回到野外")


def run_open_alliance_help(app, serial: str, toast, log,
                           threshold: float | None = None, verbose: bool = False):
    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    for key in ["alliance", "alliance_war", "auto_join", "shoucang", "daiban", "xingjun", "diaoxian"]:
        if not os.path.isfile(paths[key]):
            toast(f"缺少模板：{paths[key]}")
            return

    if not _ensure_in_wild(app, serial, paths, thr, toast, log, verbose):
        return

    png = _screencap(app, serial)
    if png is None:
        toast("无法截图，已终止任务")
        return

    ok, _ = _tap_img(app, serial, png, paths["alliance"], thr, log, "pic/alliance.png", wait_s=2.0)
    if not ok:
        if _exist(png, paths["diaoxian"], thr):
            toast("检测到掉线，请手动处理")
        else:
            toast("未找到联盟按钮")
        return

    png = _screencap(app, serial)
    if png is None:
        toast("无法截图，已终止任务")
        return

    ok, _ = _tap_img(app, serial, png, paths["alliance_war"], thr, log, "pic/alliance_war.png", wait_s=1.0)
    if not ok:
        if _exist(png, paths["diaoxian"], thr):
            toast("检测到掉线，请手动处理")
        else:
            toast("未找到联盟战入口")
        return

    log("[GARRISON] 点击坐标 (355, 1212)")
    _tap(app, serial, 355, 1212)
    _sleep(app, 1.0)
    log("[GARRISON] 点击坐标 (505, 1083)")
    _tap(app, serial, 505, 1083)
    _sleep(app, 1.0)
    for i in range(3):
        app.adb.input_back(serial)
        log(f"[GARRISON] 发送第 {i+1}/3 次返回键")
        _sleep(app, 0.3)

    png = _screencap(app, serial)
    if png is None or not _in_wild(png, paths, thr):
        log("[GARRISON] 返回后未确认在野外（忽略）")
    else:
        log("[GARRISON] 已确认回到野外")


def run_auto_garrison(app, serial: str, mode: str, toast, log, should_stop,
                      threshold: float | None = None, verbose: bool = False):
    """自动驻军主流程"""
    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    required = [
        "alliance", "alliance_war", "auto_join", "goto", "ruins", "zhanling",
        "goto_search", "chuzheng_blue_2", "shoucang", "daiban", "xingjun", "diaoxian"
    ]
    for key in required:
        if not os.path.isfile(paths[key]):
            toast(f"缺少模板：{paths[key]}")
            return

    if not _ensure_in_wild(app, serial, paths, thr, toast, log, verbose):
        return

    log("[GARRISON] 开始主循环，目标出征队列达到 6")
    queue_cnt = 0
    need_reset = False

    while queue_cnt < 6:
        if need_reset:
            if not _ensure_in_wild(app, serial, paths, thr, toast, log, verbose):
                return
            need_reset = False

        log(f"[GARRISON] 主循环开始，当前队列：{queue_cnt}/6")
        if should_stop():
            log("[GARRISON] 收到停止指令，结束自动驻军")
            return

        log(f"[GARRISON] 第 {queue_cnt + 1}/6 次出征流程启动")

        log("[GARRISON] 第三步：填写坐标")
        log("[GARRISON] 点击坐标输入框 (326, 1064)")
        app.adb.input_tap(serial, 326, 1064)
        _sleep(app, 0.3)
        log("[GARRISON] 点击 X 坐标输入框 (246, 618)")
        app.adb.input_tap(serial, 246, 618)
        _sleep(app, 0.3)
        for _ in range(4):
            app.adb.input_keyevent(serial, 67)
            _sleep(app, 0.05)
        _sleep(app, 0.3)
        x_val = random.randint(570, 629)
        log(f"[GARRISON] 输入 X 坐标：{x_val}")
        app.adb.input_text(serial, str(x_val))
        _sleep(app, 0.3)
        log("[GARRISON] 点击 Y 坐标输入框 (512, 618)")
        app.adb.input_tap(serial, 512, 618)
        _sleep(app, 0.3)
        for _ in range(4):
            app.adb.input_keyevent(serial, 67)
            _sleep(app, 0.05)
        _sleep(app, 0.3)
        y_val = random.randint(373, 432)
        log(f"[GARRISON] 输入 Y 坐标：{y_val}")
        app.adb.input_text(serial, str(y_val))
        log(f"[GARRISON] 坐标输入完成 ({x_val}, {y_val})")

        log("[GARRISON] 第四步：查找并点击 goto.png")
        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，已终止任务")
            return
        ok, pos = _match_one(png, paths["goto"], thr)
        if ok:
            log(f"[GARRISON] 找到 goto.png，位置：{pos}")
            _tap(app, serial, *pos)
            _sleep(app, 0.2)
            _tap(app, serial, 364, 636)
            _sleep(app, 0.2)
        else:
            if _exist(png, paths["diaoxian"], thr):
                toast("检测到掉线，请手动处理")
                return
            log("[GARRISON] 未找到 goto.png，本轮回到第一步重试")
            need_reset = True
            continue

        log("[GARRISON] 第五步：检测 ruins.png 与 zhanling.png")
        _sleep(app, 0.5)
        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，已终止任务")
            return
        has_ruins = _exist(png, paths["ruins"], thr)
        has_zl = _exist(png, paths["zhanling"], thr)
        log(f"[GARRISON] 检测结果：ruins={has_ruins} zhanling={has_zl}")
        if has_ruins and has_zl:
            ok, pos = _match_one(png, paths["zhanling"], thr)
            if ok:
                _tap(app, serial, *pos)
                log(f"[GARRISON] 点击占领按钮，位置：{pos}")
                queue_cnt += 1
                log(f"[GARRISON] 已确认占领，当前计数：{queue_cnt}/6")
            else:
                if _exist(png, paths["diaoxian"], thr):
                    toast("检测到掉线，请手动处理")
                    return
                log("[GARRISON] 未定位到 zhanling.png，本轮回到第一步重试")
                need_reset = True
                continue
        else:
            if _exist(png, paths["diaoxian"], thr):
                toast("检测到掉线，请手动处理")
                return
            log("[GARRISON] 未同时检测到 ruins 与 zhanling，本轮回到第一步重试")
            need_reset = True
            continue

        log("[GARRISON] 第六步：检测 goto_search.png")
        _sleep(app, 0.5)
        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，已终止任务")
            return
        if _exist(png, paths["goto_search"], thr):
            log("[GARRISON] 检测到 goto_search，任务结束")
            return

        if mode == "joy":
            log("[GARRISON] 乔伊模式：执行智能选兵")
            from ...tasks.new_troop_selection import run_new_troop_selection
            workers = getattr(app, 'workers', None)
            device_worker = workers.get(serial) if workers else None
            if device_worker is None:
                toast("设备不在线，无法执行智能选兵")
                return
            run_new_troop_selection(device_worker, log)
            log("[GARRISON] 智能选兵完成")
        else:
            log("[GARRISON] 收菜模式：跳过智能选兵")

        log("[GARRISON] 第七步：查找并点击 chuzheng_blue_2.png")
        png = _screencap(app, serial)
        if png is None:
            toast("无法截图，已终止任务")
            return
        ok, pos = _match_one(png, paths["chuzheng_blue_2"], thr)
        if ok:
            _tap(app, serial, *pos)
            log(f"[GARRISON] 点击出征按钮，位置：{pos}")
        else:
            if _exist(png, paths["diaoxian"], thr):
                toast("检测到掉线，请手动处理")
                return
            log("[GARRISON] 未找到出征按钮，本轮回到第一步重试")
            need_reset = True
            continue

        need_reset = True
        log(f"[GARRISON] 本轮流程结束，当前队列：{queue_cnt}/6，准备回到第一步")

    toast("自动驻军完成：队列已达 6")
