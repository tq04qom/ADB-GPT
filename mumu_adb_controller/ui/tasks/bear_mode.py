# mumu_adb_controller/ui/tasks/bear_mode.py
import os
import sys
import time
import random
import datetime as _dt
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from ..helpers import matcher
from .withdraw_troops import run_withdraw_troops
from .auto_garrison import run_close_alliance_help
from .init_to_wild import run_init_to_wild


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
SEAT_CANDIDATES: Tuple[Tuple[int, int], ...] = ((68, 120), (142, 116), (218, 115))
JOIN_THRESHOLD = 0.97


@dataclass
class BearOptions:
    target_time: _dt.time
    day_mode: str          # "odd" / "even" / "both"
    send_car: bool
    head_mode: str         # "fixed" / "random"
    interval_sec: int
    delay_sec: int = 0     # 延迟发车秒数（仅首次发车有效）


class BearRuntime:
    def __init__(self, app, serial: str, toast: Callable[[str], None], log: Callable[[str], None],
                 should_stop: Callable[[], bool], options: BearOptions,
                 threshold: Optional[float], verbose: bool):
        self.app = app
        self.serial = serial
        self.toast = toast
        self.log = log
        self.should_stop = should_stop
        self.options = options
        self.threshold = matcher.THRESH if threshold is None else float(threshold)
        self.verbose = verbose
        self.pause_event = getattr(app, "pause_event", None)
        self._head_templates: Optional[List[str]] = None
        self._seat_index = 0

    # ---------- 通用工具 ----------
    def now(self) -> float:
        return time.time()

    def _sleep_with_pause(self, seconds: float) -> bool:
        end = self.now() + max(0.0, seconds)
        while self.now() < end:
            if self.should_stop():
                return True
            while self.pause_event is not None and self.pause_event.is_set():
                if self.should_stop():
                    return True
                time.sleep(0.05)
            time.sleep(min(0.1, end - self.now()))
        return False

    def wait_until(self, target_ts: float, label: str = "") -> bool:
        while self.now() < target_ts:
            if self.should_stop():
                return True
            remaining = max(0.0, target_ts - self.now())
            self._sleep_with_pause(min(0.5, remaining))
        if label:
            self.log(f"[BEAR] 到达时间点：{label}")
        return False

    def _screencap(self) -> Optional[bytes]:
        ok, data = self.app.adb.screencap(self.serial)
        return data if ok and data else None

    def _tap(self, x: int, y: int):
        self.app.adb.input_tap(self.serial, int(x), int(y))

    def _swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 600):
        self.app.adb.input_swipe(self.serial, x1, y1, x2, y2, duration)

    def _swipe_hold(self, start: Tuple[int, int], end: Tuple[int, int], hold_ms: int = 500, pause_ms: int = 500):
        sx, sy = start
        ex, ey = end
        # 按住起点，移动到终点并保持
        self.app.adb.input_swipe(self.serial, sx, sy, ex, ey, max(1, hold_ms))
        self._sleep_with_pause(pause_ms / 1000.0)

    def _send_back(self):
        """发送返回键命令"""
        self.app.adb.input_back(self.serial)

    def ensure_in_wild(self) -> bool:
        run_init_to_wild(
            self.app, self.serial,
            toast=self.toast,
            log=self.log,
            threshold=self.threshold,
            verbose=self.verbose,
        )
        return True

    def _load_head_templates(self) -> List[str]:
        if self._head_templates is not None:
            return self._head_templates
        base = res_path("pic", "head")
        files: List[str] = []
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if name.lower().endswith(".png"):
                    files.append(os.path.join(base, name))
        self._head_templates = files
        return files

    # ---------- 上车座位选择 ----------
    def pick_seat(self) -> Tuple[int, int]:
        mode = self.options.head_mode
        if mode == "fixed":
            # 固定车头模式：轮流选择三个座位
            seat = SEAT_CANDIDATES[self._seat_index % len(SEAT_CANDIDATES)]
            self._seat_index += 1
            return seat
        if mode == "random":
            idx = random.randrange(len(SEAT_CANDIDATES))
            return SEAT_CANDIDATES[idx]
        seat = SEAT_CANDIDATES[self._seat_index % len(SEAT_CANDIDATES)]
        self._seat_index += 1
        return seat


def _check_required_templates(options: BearOptions) -> Tuple[bool, List[str]]:
    required = [
        P("xiong.png"),
        P("xiong_jijie.png"),
        P("faqijijie.png"),
        P("chuzheng_blue_2.png"),
        P("alliance.png"),
        P("alliance_war.png"),
        P("alliance_war2.png"),
        P("join.png"),
        P("small_join.png"),
        P("jijie_inside.png"),
        P("goto_search.png"),
    ]
    missing = [p for p in required if not os.path.isfile(p)]
    return (len(missing) == 0, missing)


def _match_one(png: bytes, path: str, thr: float):
    return matcher.match_one(png, path, threshold=thr)


def _wait_for_image(ctx: BearRuntime, path: str, timeout: float, interval: float, label: str) -> Tuple[bool, Tuple[int, int]]:
    deadline = ctx.now() + timeout
    while ctx.now() <= deadline:
        if ctx.should_stop():
            return False, (0, 0)
        png = ctx._screencap()
        if png:
            ok, pos = _match_one(png, path, ctx.threshold)
            if ok:
                ctx.log(f"[BEAR] 找到 {label} @ {pos}")
                return True, pos
        if ctx._sleep_with_pause(interval):
            return False, (0, 0)
    ctx.log(f"[BEAR] 等待 {label} 超时")
    return False, (0, 0)


def _send_withdraw(ctx: BearRuntime):
    ctx.log("[BEAR] 执行一键撤军")
    run_withdraw_troops(
        ctx.app, ctx.serial,
        toast=ctx.toast,
        log=ctx.log,
        threshold=ctx.threshold,
        verbose=ctx.verbose,
        should_stop=ctx.should_stop,
    )


def _close_auto_join(ctx: BearRuntime):
    ctx.log("[BEAR] 执行关闭上车")
    run_close_alliance_help(
        ctx.app, ctx.serial,
        toast=ctx.toast,
        log=ctx.log,
        threshold=ctx.threshold,
        verbose=ctx.verbose,
    )


def _click_template(ctx: BearRuntime, png: bytes, path: str, label: str, wait_sec: float = 0.0) -> bool:
    ok, pos = _match_one(png, path, ctx.threshold)
    if ok:
        ctx.log(f"[BEAR] 点击 {label} @ {pos}")
        ctx._tap(*pos)
        if wait_sec > 0:
            ctx._sleep_with_pause(wait_sec)
        return True
    return False


def _locate_xiong(ctx: BearRuntime, max_attempts: int = 5) -> Optional[Tuple[int, int]]:
    deadline = ctx.now() + max_attempts * 1.5
    for attempt in range(max_attempts):
        if ctx.should_stop() or ctx.now() >= deadline:
            break
        png = ctx._screencap()
        if png:
            ok, pos = _match_one(png, P("xiong.png"), ctx.threshold)
            if ok:
                ctx.log(f"[BEAR] 第 {attempt + 1} 次检测到熊图 @ {pos}")
                return pos
        ctx.log(f"[BEAR] 第 {attempt + 1} 次未找到熊图，1 秒后重试")
        if ctx._sleep_with_pause(1.0):
            return None
    ctx.log("[BEAR] 连续5次未检测到熊图")
    return None


def _execute_send_sequence(ctx: BearRuntime, initial_pos: Optional[Tuple[int, int]] = None) -> bool:
    pos = initial_pos if initial_pos is not None else _locate_xiong(ctx)
    if pos is None:
        return False
    ctx._tap(*pos)
    ctx._sleep_with_pause(1.0)
    png = ctx._screencap()
    if not png:
        ctx.log("[BEAR] 熊界面截图失败")
        return False
    if not _click_template(ctx, png, P("xiong_jijie.png"), "熊集结", wait_sec=0.3):
        ctx.log("[BEAR] 未找到熊集结按钮")
        return False
    png = ctx._screencap()
    if not png:
        ctx.log("[BEAR] 发起集结界面截图失败")
        return False
    if not _click_template(ctx, png, P("faqijijie.png"), "发起集结", wait_sec=0.3):
        ctx.log("[BEAR] 未找到发起集结按钮")
        return False
    ctx._tap(289, 113)
    ctx._sleep_with_pause(0.3)
    png = ctx._screencap()
    if not png:
        ctx.log("[BEAR] 出征确认界面截图失败")
        return False
    if not _click_template(ctx, png, P("chuzheng_blue_2.png"), "出征按钮"):
        ctx.log("[BEAR] 未找到出征按钮")
        return False
    return True


def _perform_send_cycle(ctx: BearRuntime, end_ts: float) -> Tuple[str, Optional[float]]:
    ctx.log("[BEAR] 发车流程启动")
    ctx.ensure_in_wild()
    first_pos = _locate_xiong(ctx)
    if first_pos is None:
        ctx.log("[BEAR] 连续5次未检测到熊图，跳过发车进入上车流程")
        return "skip", None
    for attempt in range(3):
        if ctx.should_stop() or ctx.now() >= end_ts:
            break
        if attempt > 0:
            ctx.log(f"[BEAR] 发车重试第 {attempt + 1} 次")
            ctx.ensure_in_wild()
        success = _execute_send_sequence(ctx, initial_pos=first_pos if attempt == 0 else None)
        if success:
            ctx.log("[BEAR] 发车完成")
            return "success", None
    ctx.log("[BEAR] 三次发车尝试仍未成功，转入上车流程，30秒后再次尝试发车")
    return "retry", 30.0


def _ensure_alliance_war(ctx: BearRuntime, depart_deadline: Optional[float]) -> str:
    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due"
    ctx.ensure_in_wild()
    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due"

    png = ctx._screencap()
    if png and _click_template(ctx, png, P("alliance.png"), "联盟入口", wait_sec=0.2):
        pass
    else:
        ctx.log("[BEAR] 未匹配到联盟按钮，尝试直接点击常用坐标")
        ctx._tap(1180, 660)
    if ctx._sleep_with_pause(2.0):
        return "stopped"
    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due"

    png = ctx._screencap()
    if not png:
        return "retry"
    if not _click_template(ctx, png, P("alliance_war.png"), "联盟战争", wait_sec=0.5):
        ctx.log("[BEAR] 未匹配到联盟战争入口")
        return "retry"

    png = ctx._screencap()
    if not png:
        return "retry"
    ok, _ = _match_one(png, P("alliance_war2.png"), ctx.threshold)
    if not ok:
        ctx.log("[BEAR] 未检测到联盟战争界面标识，重试")
        return "retry"
    return "ready"


def _process_head_once(ctx: BearRuntime, depart_deadline: Optional[float]) -> Tuple[str, bool]:
    def _post_checks() -> Tuple[str, bool]:
        if depart_deadline and ctx.now() >= depart_deadline:
            return "depart_due", False
        png2 = ctx._screencap()
        if not png2:
            return "retry", False
        ok_small, pos_small = _match_one(png2, P("small_join.png"), JOIN_THRESHOLD)
        if ok_small:
            ctx.log(f"[BEAR] 额外检测到 small_join @ {pos_small}，尝试点击")
            ctx._tap(*pos_small)
            if ctx._sleep_with_pause(0.2):
                return "stopped", False
            return "retry", True
        ok_inside, pos_inside = _match_one(png2, P("jijie_inside.png"), ctx.threshold)
        if ok_inside:
            ctx.log("[BEAR] 检测到集结内部界面，准备重新初始化")
            return "restart", False
        ok_goto, _ = _match_one(png2, P("goto_search.png"), ctx.threshold)
        if ok_goto:
            ctx.log("[BEAR] 检测到集结界面的查找按钮，准备重新初始化")
            return "restart", False
        return "retry", False
    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due", False
    png = ctx._screencap()
    if not png:
        return "retry", False
    join_thr = max(ctx.threshold, JOIN_THRESHOLD)
    mode = ctx.options.head_mode
    if mode == "fixed":
        heads = ctx._load_head_templates()
        if not heads:
            ctx.log("[BEAR] 未配置任何头部模板，跳过上车检测")
            return "no_templates", False

        for tpl in heads:
            ok, (x, y) = _match_one(png, tpl, ctx.threshold)
            if ok:
                ctx.log(f"[BEAR] 匹配到头部 {os.path.basename(tpl)} @ ({x},{y})")
                # 在头部附近的 ROI 内（x..x+720, y..y+240）直接裁剪后匹配 join.png
                roi_x1, roi_y1 = x, y
                roi_x2, roi_y2 = x + 720, y + 240
                join_ok, join_pos = matcher.match_in_range(png, P("join.png"), ((roi_x1, roi_y1), (roi_x2, roi_y2)), threshold=join_thr)
                if join_ok:
                    jx, jy = join_pos
                    ctx.log(f"[BEAR] 在头部附近检测到 join.png @ {join_pos}，直接点击")
                    ctx._tap(jx, jy)
                    if ctx._sleep_with_pause(0.2):
                        return "stopped", False
                    seat = ctx.pick_seat()
                    ctx._tap(*seat)
                    ctx.log(f"[BEAR] 选择座位 {seat}")
                    if ctx._sleep_with_pause(0.3):
                        return "stopped", True
                    confirm_png = ctx._screencap()
                    if confirm_png and _click_template(ctx, confirm_png, P("chuzheng_blue_2.png"), "出征确认"):
                        ctx.log("[BEAR] 完成一次上车")
                        return "joined", True
                    ctx.log("[BEAR] 未找到出征确认按钮，尝试继续")
                    return _post_checks()
                else:
                    ctx.log("[BEAR] 未在头部附近检测到 join.png，继续匹配下一个模板")
                    continue
        status, flag = _post_checks()
        if status != "retry":
            return status, flag
        return "no_head", False

    ok, (xj, yj) = _match_one(png, P("join.png"), join_thr)
    if ok:
        ctx.log(f"[BEAR] 匹配到 join.png @ ({xj},{yj})")
        ctx._tap(xj, yj)
        if ctx._sleep_with_pause(0.2):
            return "stopped", False
        seat = ctx.pick_seat()
        ctx._tap(*seat)
        ctx.log(f"[BEAR] 随机座位 {seat}")
        if ctx._sleep_with_pause(0.3):
            return "stopped", True
        confirm_png = ctx._screencap()
        if confirm_png and _click_template(ctx, confirm_png, P("chuzheng_blue_2.png"), "出征确认"):
            ctx.log("[BEAR] 完成一次随机上车")
            return "joined", True
        ctx.log("[BEAR] 未找到出征确认按钮（随机上车），继续重试")
        return _post_checks()
    status, flag = _post_checks()
    if status != "retry":
        return status, flag
    return "no_join", False


def _run_join_cycle(ctx: BearRuntime, end_ts: float, depart_deadline: Optional[float]) -> str:
    stage = _ensure_alliance_war(ctx, depart_deadline)
    if stage == "depart_due":
        return "depart_due"
    if stage in {"retry", "stopped"}:
        return stage

    scroll_attempts = 0
    processed = False
    mode = ctx.options.head_mode
    while ctx.now() < end_ts:
        if depart_deadline and ctx.now() >= depart_deadline:
            return "depart_due"
        status, joined = _process_head_once(ctx, depart_deadline)
        if status == "depart_due":
            return "depart_due"
        if status == "stopped":
            return "stopped"
        if status == "restart":
            ctx.ensure_in_wild()
            return "retry"
        if status == "joined":
            processed = True
            continue
        if status == "no_templates":
            return "idle"
        if status == "retry":
            continue
        if status == "no_head" and mode == "fixed":
            if scroll_attempts >= 5:
                break
            ctx.log("[BEAR] 当前页未找到头部，执行一次下拉刷新")
            ctx._swipe_hold((367, 964), (367, 414), hold_ms=500, pause_ms=500)
            ctx._sleep_with_pause(1.0)
            scroll_attempts += 1
            if ctx._sleep_with_pause(0.6):
                return "stopped"
            continue
        if status == "no_join" and mode != "fixed":
            if scroll_attempts >= 5:
                break
            ctx.log("[BEAR] 未检测到 join.png，执行滚动刷新后继续搜索")
            ctx._swipe_hold((367, 964), (367, 414), hold_ms=500, pause_ms=500)
            ctx._sleep_with_pause(1.0)
            scroll_attempts += 1
            if ctx._sleep_with_pause(0.6):
                return "stopped"
            continue
        if ctx.should_stop():
            return "stopped"
    return "processed" if processed else "idle"


def run_bear_mode(app, serial: str,
                  toast: Callable[[str], None],
                  log: Callable[[str], None],
                  should_stop: Callable[[], bool],
                  options: BearOptions,
                  threshold: Optional[float] = None,
                  verbose: bool = False):
    if not matcher.has_cv():
        toast("缺少 opencv-python 依赖，无法运行打熊模式")
        return

    ok, missing = _check_required_templates(options)
    if not ok:
        toast(f"缺少模板文件：{', '.join(missing)}")
        return

    today = _dt.date.today()
    if options.day_mode == "odd" and today.day % 2 == 0:
        log("[BEAR] 今日为双日，配置为单日打熊，任务结束")
        toast("今日非指定打熊日期")
        return
    if options.day_mode == "even" and today.day % 2 != 0:
        log("[BEAR] 今日为单日，配置为双日打熊，任务结束")
        toast("今日非指定打熊日期")
        return

    now_dt = _dt.datetime.now()
    target_dt = _dt.datetime.combine(today, options.target_time)
    end_dt = target_dt + _dt.timedelta(minutes=25)
    if now_dt > end_dt:
        log("[BEAR] 已超过设定时间25分钟窗口，任务结束")
        toast("设定时间已过25分钟，未执行打熊流程")
        return

    skip_pre = now_dt >= target_dt

    ctx = BearRuntime(app, serial, toast, log, should_stop, options, threshold, verbose)
    toast("打熊模式已启动")
    log(f"[BEAR] 打熊开始时间：{target_dt.strftime('%H:%M:%S')} 发送车：{options.send_car} 间隔：{options.interval_sec}s")

    if skip_pre:
        log("[BEAR] 当前已处于打熊时段，跳过撤军准备直接进入主流程")
    else:
        pre_times = [target_dt - _dt.timedelta(minutes=10 - 2 * i) for i in range(4)]
        for ts in pre_times:
            if ctx.should_stop():
                return
            if ts < now_dt:
                continue
            ctx.log(f"[BEAR] 等待撤军时刻：{ts.strftime('%H:%M:%S')}")
            if ctx.wait_until(ts.timestamp(), label="撤军时刻"):
                return
            _send_withdraw(ctx)

        if ctx.should_stop():
            return
        _close_auto_join(ctx)
    ctx.ensure_in_wild()

    pre_depart_ts = (target_dt - _dt.timedelta(seconds=30)).timestamp()
    if ctx.now() < pre_depart_ts:
        ctx.log("[BEAR] 等待开打前30秒")
        if ctx.wait_until(pre_depart_ts, label="开打前30秒"):
            return

    if not options.send_car:
        ctx.log("[BEAR] 配置为只上车，提前进入联盟界面")
    ctx.ensure_in_wild()

    end_ts = end_dt.timestamp()

    # 判断是否使用新版固定车头逻辑
    use_new_fixed_logic = (options.head_mode == "fixed")

    if use_new_fixed_logic:
        ctx.log("[BEAR] 使用新版固定车头逻辑")
        _run_new_fixed_bear_mode(ctx, target_dt, end_ts, options)
    else:
        ctx.log("[BEAR] 使用随机上车逻辑")
        _run_random_bear_mode(ctx, target_dt, end_ts, options)

    toast("打熊模式已完成")
    log("[BEAR] 打熊模式结束（达到结束时间或收到停止指令）")


def _run_random_bear_mode(ctx: BearRuntime, target_dt: _dt.datetime, end_ts: float, options: BearOptions):
    """随机上车模式（原逻辑不变）"""
    depart_deadline = target_dt.timestamp() if options.send_car else None

    if options.send_car:
        if ctx.wait_until(target_dt.timestamp(), label="开打时间"):
            return
        if ctx.should_stop():
            return
        status, wait_next = _perform_send_cycle(ctx, end_ts)
        if status == "success":
            depart_deadline = ctx.now() + options.interval_sec
        elif status == "retry":
            depart_deadline = ctx.now() + (wait_next or 30.0)
        elif status == "skip":
            depart_deadline = ctx.now() + options.interval_sec
        else:
            return

    while not ctx.should_stop() and ctx.now() < end_ts:
        if options.send_car and depart_deadline and ctx.now() >= depart_deadline:
            status, wait_next = _perform_send_cycle(ctx, end_ts)
            if status == "success":
                depart_deadline = ctx.now() + options.interval_sec
                continue
            if status == "retry":
                depart_deadline = ctx.now() + (wait_next or 30.0)
                continue
            if status == "skip":
                depart_deadline = ctx.now() + options.interval_sec
                continue
            return

        result = _run_join_cycle(ctx, end_ts, depart_deadline)
        if result == "depart_due":
            continue
        if result == "stopped":
            return
        if result == "retry":
            ctx._sleep_with_pause(1.0)
            continue
        if result == "idle":
            wait_window = 2.0
            if options.send_car and depart_deadline:
                wait_window = min(wait_window, max(0.5, depart_deadline - ctx.now()))
            ctx._sleep_with_pause(wait_window)


def _run_new_fixed_bear_mode(ctx: BearRuntime, target_dt: _dt.datetime, end_ts: float, options: BearOptions):
    """新版固定车头模式逻辑"""
    if not options.send_car:
        ctx.log("[BEAR] 固定车头模式但未启用发车，仅执行上车")
        while not ctx.should_stop() and ctx.now() < end_ts:
            result = _run_fixed_join_cycle(ctx, end_ts, None)
            if result == "stopped":
                return
            if result == "idle":
                ctx._sleep_with_pause(1.0)
        return

    # 计算首次发车时间（开打时间 + 延迟秒数）
    first_depart_time = target_dt.timestamp() + options.delay_sec
    ctx.log(f"[BEAR] 首次发车时间：{_dt.datetime.fromtimestamp(first_depart_time).strftime('%H:%M:%S')} (延迟{options.delay_sec}秒)")

    # 等待到开打时间
    if ctx.wait_until(target_dt.timestamp(), label="开打时间"):
        return

    # 2.1 发车前的上车流程
    ctx.log("[BEAR] 开始发车前上车流程")
    while not ctx.should_stop() and ctx.now() < first_depart_time:
        remaining = first_depart_time - ctx.now()
        if remaining <= 0:
            break

        ctx.log(f"[BEAR] 距离首次发车还有 {remaining:.1f} 秒")
        result = _run_fixed_join_cycle(ctx, first_depart_time, first_depart_time)

        if result == "depart_due":
            ctx.log("[BEAR] 到达首次发车时间，停止上车")
            break
        if result == "stopped":
            return
        if result == "idle":
            # 等待一小段时间后继续
            wait_time = min(1.0, first_depart_time - ctx.now())
            if wait_time > 0:
                ctx._sleep_with_pause(wait_time)

    # 2.1.2 首次发车
    if ctx.should_stop() or ctx.now() >= end_ts:
        return

    ctx.log("[BEAR] 执行首次发车")
    status, _ = _perform_send_cycle(ctx, end_ts)

    if status not in {"success", "skip"}:
        ctx.log("[BEAR] 首次发车失败，继续上车流程")

    # 记录发车时间，设置下次发车deadline
    last_depart_time = ctx.now()
    next_depart_deadline = last_depart_time + options.interval_sec
    ctx.log(f"[BEAR] 下次发车时间：{_dt.datetime.fromtimestamp(next_depart_deadline).strftime('%H:%M:%S')}")

    # 2.2 主循环：上车 + 定时发车
    while not ctx.should_stop() and ctx.now() < end_ts:
        # 检查是否到达发车时间
        if ctx.now() >= next_depart_deadline:
            ctx.log("[BEAR] 到达发车时间，执行初始化到野外")
            ctx.ensure_in_wild()

            if ctx.should_stop() or ctx.now() >= end_ts:
                return

            ctx.log("[BEAR] 执行定时发车")
            status, _ = _perform_send_cycle(ctx, end_ts)

            # 更新下次发车时间
            last_depart_time = ctx.now()
            next_depart_deadline = last_depart_time + options.interval_sec
            ctx.log(f"[BEAR] 下次发车时间：{_dt.datetime.fromtimestamp(next_depart_deadline).strftime('%H:%M:%S')}")
            continue

        # 执行上车流程
        result = _run_fixed_join_cycle(ctx, end_ts, next_depart_deadline)

        if result == "depart_due":
            # 到达发车时间，回到循环开始处理发车
            continue
        if result == "stopped":
            return
        if result == "idle":
            # 等待一小段时间后继续
            wait_time = min(1.0, next_depart_deadline - ctx.now())
            if wait_time > 0:
                ctx._sleep_with_pause(wait_time)


# ==================== 新版固定车头模式逻辑 ====================

def _scroll_to_bottom(ctx: BearRuntime) -> bool:
    """拉到最底端：从(350, 1037)向上拖动700像素"""
    ctx._swipe(350, 1037, 350, 337, duration=100)  # 快速拖动
    return ctx._sleep_with_pause(0.1)


def _check_in_alliance_war_list(ctx: BearRuntime) -> bool:
    """检查是否在出征列表界面"""
    png = ctx._screencap()
    if not png:
        return False
    ok, _ = _match_one(png, P("alliance_war2.png"), ctx.threshold)
    return ok


def _init_to_alliance_war_list(ctx: BearRuntime, depart_deadline: Optional[float]) -> str:
    """2.2.1 初始化到出征列表界面"""
    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due"

    ctx.log("[BEAR] 初始化到出征列表")
    ctx.ensure_in_wild()

    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due"

    # 点击联盟入口
    png = ctx._screencap()
    if png and _click_template(ctx, png, P("alliance.png"), "联盟入口", wait_sec=2.0):
        pass
    else:
        ctx.log("[BEAR] 未匹配到联盟按钮，点击常用坐标")
        ctx._tap(1180, 660)
        ctx._sleep_with_pause(2.0)

    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due"

    # 点击联盟战争
    png = ctx._screencap()
    if not png:
        return "retry"
    if not _click_template(ctx, png, P("alliance_war.png"), "联盟战争"):
        ctx.log("[BEAR] 未匹配到联盟战争入口")
        return "retry"

    ctx._sleep_with_pause(0.5)

    # 拉到最底端（3次）
    for i in range(3):
        if _scroll_to_bottom(ctx):
            return "stopped"

    # 检查是否在出征列表界面
    if not _check_in_alliance_war_list(ctx):
        ctx.log("[BEAR] 未检测到出征列表界面，重新初始化")
        return "retry"

    ctx.log("[BEAR] 成功进入出征列表界面")
    return "ready"


def _find_head_and_join(ctx: BearRuntime, depart_deadline: Optional[float]) -> Tuple[str, bool]:
    """2.2.3 轮流查询车头并上车

    返回: (status, joined)
    - status: "depart_due" | "stopped" | "joined" | "no_head" | "not_in_list"
    - joined: 是否成功上车
    """
    if depart_deadline and ctx.now() >= depart_deadline:
        return "depart_due", False

    # 检查是否在出征列表界面
    if not _check_in_alliance_war_list(ctx):
        ctx.log("[BEAR] 不在出征列表界面")
        return "not_in_list", False

    png = ctx._screencap()
    if not png:
        return "no_head", False

    # 在指定区域查找车头
    heads = ctx._load_head_templates()
    if not heads:
        ctx.log("[BEAR] 未配置车头模板")
        return "no_head", False

    join_thr = max(ctx.threshold, JOIN_THRESHOLD)

    for tpl in heads:
        ok_head, (hx, hy) = _match_one(png, tpl, ctx.threshold)
        if not ok_head:
            continue

        # 检查车头是否在指定区域 (235, 590) 到 (685, 1097)
        if not (235 <= hx <= 685 and 590 <= hy <= 1097):
            continue

        ctx.log(f"[BEAR] 在区域内找到车头 {os.path.basename(tpl)} @ ({hx},{hy})")

        # 查找 join.png（匹配度0.97）
        join_ok, join_pos, join_score = matcher.match_one_detail(png, P("join.png"), threshold=join_thr)
        if not join_ok or join_score < 0.97:
            ctx.log(f"[BEAR] 未找到匹配的 join.png (score={join_score:.3f})")
            continue

        jx, jy = join_pos
        ctx.log(f"[BEAR] 找到 join.png @ ({jx},{jy}), score={join_score:.3f}")

        # 点击 join
        ctx._tap(jx, jy)
        if ctx._sleep_with_pause(0.2):
            return "stopped", False

        # 选择座位（轮流选择）
        seat = ctx.pick_seat()
        ctx._tap(*seat)
        ctx.log(f"[BEAR] 选择座位 {seat}")
        if ctx._sleep_with_pause(0.3):
            return "stopped", True

        # 点击出征确认
        confirm_png = ctx._screencap()
        if confirm_png and _click_template(ctx, confirm_png, P("chuzheng_blue_2.png"), "出征确认"):
            ctx.log("[BEAR] 完成一次上车")
            return "joined", True

        ctx.log("[BEAR] 未找到出征确认按钮")
        return "joined", False

    return "no_head", False


def _run_fixed_join_cycle(ctx: BearRuntime, end_ts: float, depart_deadline: Optional[float]) -> str:
    """固定车头模式的上车循环

    返回: "depart_due" | "stopped" | "processed" | "idle"
    """
    # 2.2.1 初始化
    status = _init_to_alliance_war_list(ctx, depart_deadline)
    if status == "depart_due":
        return "depart_due"
    if status == "stopped":
        return "stopped"
    if status == "retry":
        return "idle"

    last_scroll_time = ctx.now()
    processed = False

    while ctx.now() < end_ts:
        if depart_deadline and ctx.now() >= depart_deadline:
            return "depart_due"

        if ctx.should_stop():
            return "stopped"

        # 每3秒拉到最底端
        if ctx.now() - last_scroll_time >= 3.0:
            ctx.log("[BEAR] 3秒到，拉到最底端")
            if _scroll_to_bottom(ctx):
                return "stopped"
            last_scroll_time = ctx.now()

        # 2.2.3 查找车头并上车
        status, joined = _find_head_and_join(ctx, depart_deadline)

        if status == "depart_due":
            return "depart_due"
        if status == "stopped":
            return "stopped"
        if status == "joined":
            processed = True
            # 2.2.5 返回出征列表最底端
            # 等待界面返回到出征列表（点击出征确认后有动画）
            ctx.log("[BEAR] 等待返回出征列表...")
            if ctx._sleep_with_pause(0.3):  # 等待0.3秒让动画完成
                return "stopped"

            # 检查是否在出征列表
            if _check_in_alliance_war_list(ctx):
                ctx.log("[BEAR] 上车后拉到最底端")
                if _scroll_to_bottom(ctx):
                    return "stopped"
            else:
                # 非出征列表界面，尝试发送返回键
                ctx.log("[BEAR] 上车后不在出征列表，尝试返回")
                for attempt in range(1, 4):  # 尝试3次
                    ctx._send_back()
                    if ctx._sleep_with_pause(0.3):
                        return "stopped"

                    if _check_in_alliance_war_list(ctx):
                        ctx.log(f"[BEAR] 第{attempt}次返回后检测到出征列表")
                        if _scroll_to_bottom(ctx):
                            return "stopped"
                        break
                    else:
                        ctx.log(f"[BEAR] 第{attempt}次返回后仍不在出征列表")
                else:
                    # 3次都不在，重新初始化
                    ctx.log("[BEAR] 连续3次返回后仍不在出征列表，重新初始化")
                    return "idle"
            continue
        if status == "not_in_list":
            ctx.log("[BEAR] 不在出征列表界面，重新初始化")
            return "idle"
        if status == "no_head":
            # 未找到车头，等待一小段时间后继续
            if ctx._sleep_with_pause(0.5):
                return "stopped"
            continue

    return "processed" if processed else "idle"
