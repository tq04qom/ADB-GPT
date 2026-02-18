# mumu_adb_controller/ui/tasks/promote_rank4.py
# 一键四阶（联盟功能）
import os, sys, time
from typing import Callable, Optional
from ..helpers import matcher
from .init_to_wild import build_paths as build_init_paths, run_init_to_wild

# 冻结安全资源定位
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
IMG_ALLIANCE = P("alliance.png")
IMG_MEMBER = P("member.png")
IMG_RANK_1 = P("rank_1.png")
IMG_RANK_1_1 = P("r_ank_1_1.png")  # 按你的文件名
IMG_CHANGE = P("change_rank.png")
IMG_RANK_4 = P("rank_4.png")
IMG_CONFIRM2 = P("confirm2.png")
IMG_CONFIRM_Y = P("confirm_yellow.png")


def _sleep_pause(app, sec: float):
    end = time.time() + max(0.0, float(sec))
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        while pause_ev is not None and pause_ev.is_set():
            time.sleep(0.05)
        time.sleep(min(0.1, end - time.time()))


def _wait_s(app, sec: float) -> None:
    # 引入运行速度因子：所有等待 ×speed
    try:
        speed = float(getattr(app, "get_speed_factor", lambda: 1.0)())
    except Exception:
        speed = 1.0
    _sleep_pause(app, max(0.0, sec) * max(0.01, speed))


def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _tap(app, serial, x, y):
    app.adb.input_tap(serial, int(x), int(y))


def _tap_if_found(app, serial, img_path: str, log, name: str, threshold: Optional[float] = None) -> bool:
    png = _screencap(app, serial)
    if png is None:
        log(f"[{name}] 截图失败")
        return False
    thr = matcher.THRESH if threshold is None else float(threshold)
    ok, (x, y), sc = matcher.match_one_detail(png, img_path, threshold=thr)
    base = os.path.basename(img_path)
    if ok:
        _tap(app, serial, x, y)
        log(f"[{name}] 命中 {base} score={sc:.3f}>=thr={thr:.2f} → tap({x},{y})")
        return True
    else:
        log(f"[{name}] 未命中 {base} score={sc:.3f}<thr={thr:.2f}")
        return False


def _ensure_wild(app, serial, log, thr: float) -> bool:
    # 使用 init_to_wild 的三要素进行检测
    paths = build_init_paths()
    def _check():
        png = _screencap(app, serial)
        if png is None:
            log("[R4] 截图失败（检测野外）")
            return False
        return matcher.exist_all(png, paths, ["daiban", "xingjun", "shoucang"], threshold=thr)
    if _check():
        log("[R4] 已在野外")
        return True
    # 最多 3 次尝试
    for i in range(1, 4):
        log(f"[R4] 第{i}次尝试初始化到野外…")
        run_init_to_wild(app, serial, toast=lambda m: None, log=log, threshold=thr, verbose=False)
        _wait_s(app, 3.0)
        if _check():
            log("[R4] 已进入野外")
            return True
    log("[R4] 3次仍未进入野外，放弃")
    return False


def run_promote_rank4(app, serial: str, toast: Callable[[str], None], log: Callable[[str], None],
                      should_stop: Callable[[], bool], threshold: Optional[float] = None, verbose: bool = False):
    """
    一键四阶：在联盟成员列表中将所有 rank1 → rank4。
    步骤以图片匹配驱动，严格按用户给出的等待：2s/0.5s。
    """
    thr = matcher.THRESH if threshold is None else float(threshold)

    toast("开始：一键四阶（联盟功能）")
    log("[R4] 启动：一键四阶")

    if not _ensure_wild(app, serial, log, thr):
        log("[R4] 未能进入野外，结束")
        return

    if should_stop(): return
    # 2. 进入联盟 → 成员
    _tap_if_found(app, serial, IMG_ALLIANCE, log, "R4-alliance", threshold=thr)
    _wait_s(app, 2.0)
    if should_stop(): return
    _tap_if_found(app, serial, IMG_MEMBER, log, "R4-member", threshold=thr)
    _wait_s(app, 0.5)

    if should_stop(): return
    # 3. 选 rank_1
    _tap_if_found(app, serial, IMG_RANK_1, log, "R4-rank1", threshold=thr)
    _wait_s(app, 0.5)

    promoted = 0
    # 8. 循环 4-7，直到找不到 r_ank_1_1.png
    while not should_stop():
        png = _screencap(app, serial)
        if png is None:
            log("[R4] 截图失败，结束循环")
            break
        ok, pos, sc = matcher.match_one_detail(png, IMG_RANK_1_1, threshold=thr)
        if not ok:
            log("[R4] 未见 r_ank_1_1.png，结束提升循环")
            break
        log(f"[R4] 找到 r_ank_1_1 score={sc:.3f}@{pos} → 开始提升")
        # 4. 点击 r_ank_1_1 → 等 0.5s → 点击 change_rank → 0.5s
        _tap(app, serial, pos[0], pos[1])
        _wait_s(app, 0.5)
        _tap_if_found(app, serial, IMG_CHANGE, log, "R4-change", threshold=thr)
        _wait_s(app, 0.5)
        if should_stop(): break
        # 5. rank_4
        _tap_if_found(app, serial, IMG_RANK_4, log, "R4-rank4", threshold=thr)
        _wait_s(app, 0.5)
        if should_stop(): break
        # 6. confirm2
        _tap_if_found(app, serial, IMG_CONFIRM2, log, "R4-confirm2", threshold=thr)
        _wait_s(app, 0.5)
        if should_stop(): break
        # 7. confirm_yellow
        _tap_if_found(app, serial, IMG_CONFIRM_Y, log, "R4-confirm_yellow", threshold=thr)
        _wait_s(app, 0.5)
        promoted += 1
        log(f"[R4] 已提升 {promoted} 人 → 继续查找下一位…")

    toast(f"一键四阶完成，共提升 {promoted} 人")
    log(f"[R4] 结束：共提升 {promoted} 人")

