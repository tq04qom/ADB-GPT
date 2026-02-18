# mumu_adb_controller/ui/tasks/offline_monitor.py
"""
小小号掉线监控（全局模式）

按端口两两分组（A/B），对已连接设备循环巡检：
- 情况1：A、B均掉线 → 点击A设备diaoxian.png；随后执行流程（激活“护肝神器”→点击pause→等待→掉线选人→点击confirm→对B点击diaoxian→等待→继续）
- 情况2：一台掉线一台未掉线 → 针对未掉线机器执行“掉线选人”与confirm，对掉线机器点击diaoxian；再等待、继续
- 情况3：均未掉线 → 本组本轮结束

说明：
- Windows 桌面级操作（激活窗口/点击pause/continue）尽量使用 pyautogui（可选，未安装则记录日志并跳过）。
- 设备侧操作（截图、识图、点击）通过 ADB 与 matcher 完成。
- 强制停止优先：所有等待改为可中断等待，按“停止”立即打断本轮剩余步骤。
"""
from __future__ import annotations
import os
import sys
import time
import concurrent.futures as futures
from typing import Callable, Dict, Tuple, Optional

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

THR = matcher.THRESH

# 可选：Windows 桌面点击（依赖 pyautogui）
try:
    import pyautogui  # type: ignore
    _HAS_PYAUTO = True
except Exception:
    _HAS_PYAUTO = False
# DPI 处理：Windows 缩放感知与比例查询，便于匹配前做缩放补偿
_IS_WIN = (os.name == "nt")
_DPI_AWARED = False

def _ensure_dpi_awareness():
    global _DPI_AWARED
    if not _IS_WIN or _DPI_AWARED:
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception:
        pass
    _DPI_AWARED = True

def _get_scale_factor() -> float:
    if not _IS_WIN:
        return 1.0
    try:
        import ctypes
        # 优先：GetDpiForSystem
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            if dpi:
                return max(0.5, min(4.0, dpi / 96.0))
        except Exception:
            pass
        # 退化：GetScaleFactorForMonitor
        try:
            MONITOR_DEFAULTTOPRIMARY = 1
            pt = ctypes.wintypes.POINT(0, 0)
            hmon = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY)
            scale = ctypes.c_int()
            if hasattr(ctypes.windll, 'shcore') and ctypes.windll.shcore.GetScaleFactorForMonitor(hmon, ctypes.byref(scale)) == 0:
                return max(0.5, min(4.0, scale.value / 100.0))
        except Exception:
            pass
    except Exception:
        pass
    return 1.0



def _logv(log: Callable[[str], None], msg: str, verbose: bool):
    if verbose:
        log(f"[OFFMON][DEBUG] {msg}")


def _sleep_until(should_stop: Callable[[], bool], seconds: float, step: float = 0.2) -> bool:
    """可中断睡眠；返回 True 表示期间被停止。"""
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        if should_stop():
            return True
        time.sleep(min(step, end - time.time()))
    return False



# 设备操作间延迟（按设备 serial 记录上次“操作完成”时间）
_LAST_OP_TS: Dict[str, float] = {}

def _pre_op_delay(serial: str, should_stop: Callable[[], bool] | None) -> bool:
    """
    在每次设备操作前根据与上次操作的间隔增加额外等待：
    - 若间隔 > 4s：再等待 2s
    - 若间隔 <= 4s：再等待 1s
    返回 True 表示等待过程中被停止，应放弃本次操作。
    """
    last = _LAST_OP_TS.get(serial)
    if last is None:
        return False
    gap = time.time() - last
    extra = 2.0 if gap > 4.0 else 1.0
    if should_stop:
        return _sleep_until(should_stop, extra)
    else:
        time.sleep(extra)
        return False

def _screencap(app, serial: str) -> Optional[bytes]:
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _tap(app, serial: str, x: int, y: int, sleep_s: float = 0.0, should_stop: Callable[[], bool] | None = None):
    # 操作前的额外延迟（按上次操作时间决定 1s/2s）
    if _pre_op_delay(serial, should_stop):
        return
    app.adb.input_tap(serial, int(x), int(y))
    # 操作后的原有等待（保持可中断）
    if sleep_s > 0:
        if should_stop and _sleep_until(should_stop, sleep_s):
            return
    # 记录“操作完成时间”
    _LAST_OP_TS[serial] = time.time()


def _tap_img(app, serial: str, img_path: str, thr: float, log: Callable[[str], None], name: str = "", wait_s: float = 0.0, should_stop: Callable[[], bool] | None = None) -> bool:
    if should_stop and should_stop():
        return False
    png = _screencap(app, serial)
    if not png:
        try:
            app.enqueue_to_tab(serial, f"[OFFMON] 无法截图：{serial}")
        except Exception:
            pass
        return False
    ok, pos = matcher.match_one(png, img_path, threshold=thr)
    if not ok:
        _logv(log, f"匹配失败：{name or os.path.basename(img_path)} @ {serial}", True)
        return False
    x, y = pos
    _tap(app, serial, x, y, sleep_s=wait_s, should_stop=should_stop)
    try:
        app.enqueue_to_tab(serial, f"[OFFMON] 点击 {name or os.path.basename(img_path)} at {pos} on {serial}")
    except Exception:
        pass
    return True


def _exist(app, serial: str, img_path: str, thr: float) -> bool:
    png = _screencap(app, serial)
    if not png:
        return False
    return matcher.exist(png, img_path, threshold=thr)


def _ensure_in_wild(app, serial: str, log: Callable[[str], None], thr: float, verbose: bool, should_stop: Callable[[], bool]) -> bool:
    """回到野外：最多重试3次。判定依靠三图 shoucang/daiban/xingjun 同时存在。"""
    from .init_to_wild import run_init_to_wild
    P = lambda n: res_path("pic", n)
    need = {"shoucang": P("shoucang.png"), "daiban": P("daiban.png"), "xingjun": P("xingjun.png")}

    def _in_wild() -> bool:
        png = _screencap(app, serial)
        if not png:
            return False
        return matcher.exist_all(png, need, ["shoucang", "daiban", "xingjun"], threshold=thr)

    for i in range(3):
        if should_stop():
            return False
        run_init_to_wild(app, serial, toast=lambda s: None, log=log, threshold=thr, verbose=verbose)
        if _sleep_until(should_stop, 1.0):
            return False
        if _in_wild():
            return True
        if _sleep_until(should_stop, 3.0):
            return False
    try:
        app.enqueue_to_tab(serial, f"[OFFMON] 回到野外失败（重试3次后仍未确认），serial={serial}")
    except Exception:
        pass
    return False


def _drop_line_selection(app, serial: str, log: Callable[[str], None], thr: float, verbose: bool, should_stop: Callable[[], bool]):
    """方法：掉线选人（五步），所有等待均可被中断"""
    P = lambda n: res_path("pic", n)
    if not _ensure_in_wild(app, serial, log, thr, verbose, should_stop):
        return
    if should_stop():
        return
    # 第二步：点击 (43, 43) 等待10秒
    _tap(app, serial, 43, 43, sleep_s=10.0, should_stop=should_stop)
    if should_stop():
        return
    # 第三步：点击 settings.png 等待4秒
    _tap_img(app, serial, P("settings.png"), thr, log, name="settings.png", wait_s=4.0, should_stop=should_stop)
    if should_stop():
        return
    # 第四步：点击 chacactor_choose.png 等待3秒（文件名待确认）
    _tap_img(app, serial, P("chacactor_choose.png"), thr, log, name="chacactor_choose.png", wait_s=3.0, should_stop=should_stop)
    if should_stop():
        return
    # 第五步：点击两次坐标
    _tap(app, serial, 574, 525, sleep_s=0.30, should_stop=should_stop)
    _tap(app, serial, 541, 678, sleep_s=1.0, should_stop=should_stop)


# ---------------- Windows 桌面级操作（可选） ----------------

def _activate_window_and_click(image_name: str, log: Callable[[str], None], title_keyword: str = "护肝神器", should_stop: Callable[[], bool] | None = None):
    """激活名为“护肝神器”的窗口，并在该窗口区域内查找并点击图片（若可用）。
    - 优先在“护肝神器”窗口内进行限定区域匹配以加快速度；找不到窗口时回退为全屏。
    - 支持备用图片：
      - 点击 pause.png 时，同时尝试 pause_1.png、pause_blue_1.png
      - 点击 continue.png 时，同时尝试 continue_blue.png、continue_1.png、continue_blue_1.png
    - 需要 pyautogui；未安装则记录提示并跳过。
    - 可中断：should_stop() 为 True 时立即返回。
    - 重试机制：如果未成功，尝试3次先激活窗口再找图，不成功不影响后续流程。
    """
    if should_stop and should_stop():
        return
    if not _HAS_PYAUTO:
        log("[OFFMON] 未安装 pyautogui，无法进行桌面点击：" + image_name)
        return

    # 尝试3次
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        if should_stop and should_stop():
            return

        if attempt > 1:
            log(f"[OFFMON] 第{attempt}次尝试点击 {image_name}")

        success = _try_activate_and_click_once(image_name, log, title_keyword, should_stop)
        if success:
            return  # 成功则退出

        # 失败后等待一下再重试
        if attempt < max_attempts:
            time.sleep(0.5)

    # 3次都失败，记录日志但不影响后续流程
    log(f"[OFFMON] 尝试{max_attempts}次后仍未找到 {image_name}，继续后续流程")


def _try_activate_and_click_once(image_name: str, log: Callable[[str], None], title_keyword: str = "护肝神器", should_stop: Callable[[], bool] | None = None) -> bool:
    """单次尝试激活窗口并点击图片，返回是否成功"""
    if should_stop and should_stop():
        return False
    try:
        _ensure_dpi_awareness()
        # 激活窗口并确定限定搜索区域
        w = None
        region = None  # (left, top, width, height)
        try:
            import pygetwindow as gw
            titles = [t for t in gw.getAllTitles() if t and title_keyword in t]
            if titles:
                w = gw.getWindowsWithTitle(titles[0])[0]
                try:
                    w.activate()
                    time.sleep(0.3)  # 增加等待时间，确保窗口激活
                except Exception:
                    pass
                # 计算窗口区域
                left, top, right, bottom = w.left, w.top, w.right, w.bottom
                region = (left, top, max(1, right - left), max(1, bottom - top))
        except Exception as e:
            log(f"[OFFMON] 获取窗口失败（{title_keyword}）：{type(e).__name__}: {e!r}")
        if region is None:
            log(f"[OFFMON] 未找到包含‘{title_keyword}’的窗口，退回到全屏查找：{image_name}")

        # 构造候选图片列表
        candidates = [image_name]
        if image_name == "pause.png":
            candidates.extend(["pause_1.png", "pause_blue_1.png"])
        elif image_name == "continue.png":
            candidates.extend(["continue_blue.png", "continue_1.png", "continue_blue_1.png"])
        # 仅保留存在的文件
        cand_paths = [res_path("pic", n) for n in candidates if os.path.isfile(res_path("pic", n))]
        if not cand_paths:
            log(f"[OFFMON] 缺少桌面点击图：{', '.join(candidates)}")
            return False

        # DPI：依据系统缩放调整模板尺寸（将模板按当前缩放倍数放大/缩小）
        scale = _get_scale_factor()

        def _prepare_template(pth: str):
            try:
                from PIL import Image
                img = Image.open(pth).convert("RGB")
                if abs(scale - 1.0) > 0.01:
                    img = img.resize((max(1, int(round(img.width * scale))),
                                      max(1, int(round(img.height * scale)))), Image.LANCZOS)
                return img
            except Exception:
                return pth  # 回退为路径

        # 依次尝试候选图片；总时长上限 4s，每个候选图尝试 ~2s
        overall_deadline = time.time() + 4.0
        loc = None
        hit_name = None
        for idx, pth in enumerate(cand_paths):
            if should_stop and should_stop():
                return False
            tpl = _prepare_template(pth)
            per_deadline = overall_deadline if idx == len(cand_paths) - 1 else time.time() + 2.0
            while time.time() < per_deadline and not (should_stop and should_stop()):
                try:
                    loc = pyautogui.locateCenterOnScreen(tpl, confidence=0.80, grayscale=True,
                                                          region=region)
                except Exception as ee:
                    log(f"[OFFMON] locateCenterOnScreen 异常：{type(ee).__name__}: {ee!r}")
                    break
                if loc:
                    hit_name = os.path.basename(pth)
                    break
                time.sleep(0.18)
            if loc:
                break

        if not loc:
            scope = "窗口内" if region else "全屏"
            log(f"[OFFMON] 未在{scope}找到候选：{', '.join([os.path.basename(x) for x in cand_paths])}（缩放 {scale:.2f}x）")
            return False

        pyautogui.moveTo(loc.x, loc.y, duration=0.1)
        pyautogui.click()
        scope = "窗口内" if region else "全屏"
        log(f"[OFFMON] 桌面点击（{scope}）：{hit_name} at ({loc.x},{loc.y}) [DPI {scale:.2f}]")
        return True  # 成功点击
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"[OFFMON] 桌面点击异常：{type(e).__name__}: {e!r}\n{tb}")
        return False


# ---------------- 端口分组 ----------------

def _group_ports() -> Dict[int, Tuple[int, int]]:
    """生成 1..20 组的 (A,B) 端口映射。A < B，A=16416+(i-1)*64，B=A+32"""
    base = 16416
    step_pair = 64
    delta = 32
    groups: Dict[int, Tuple[int, int]] = {}
    for i in range(1, 21):
        a = base + (i - 1) * step_pair
        b = a + delta
        groups[i] = (a, b)
    return groups


def _serial_port(serial: str) -> Optional[int]:
    # 形如 127.0.0.1:16416 或 16416
    try:
        if ":" in serial:
            return int(serial.split(":")[-1])
        return int(serial)
    except Exception:
        return None


# ---------------- 主流程 ----------------

def run_offline_monitor(app,
                        interval_minutes: int,
                        should_stop: Callable[[], bool],
                        toast: Callable[[str], None] | None,
                        log: Callable[[str], None],
                        threshold: float | None = None,
                        verbose: bool = False):
    thr = THR if threshold is None else float(threshold)
    P = lambda n: res_path("pic", n)
    paths = {
        "diaoxian": P("diaoxian.png"),
        "pause": P("pause.png"),
        "continue": P("continue.png"),
        "settings": P("settings.png"),
        "chacactor": P("chacactor_choose.png"),
        "confirm": P("confirm.png"),
    }
    notes = {}
    try:
        notes = dict(getattr(app, "cfg", {}).get("notes", {}))
    except Exception:
        notes = {}
    def _label(s: Optional[str]) -> str:
        if not s:
            return ""
        n = (notes.get(s) or "").strip()
        return f"{s}({n})" if n else s

    # 资源存在性提示（不阻塞执行）
    for k, p in paths.items():
        if not os.path.isfile(p):
            log(f"[OFFMON] 提示：缺少资源 {k}: {p}")

    groups = _group_ports()

    def info(s: str):
        if toast:
            try:
                toast(s)
            except Exception:
                pass
        log(s)

    info("[OFFMON] 启动监控，立即进行第一次掉线检测…")
    while not should_stop():
        try:
            # 构建“已连接设备”的端口→serial 映射
            port2serial: Dict[int, str] = {}
            all_serials = list(getattr(app, "workers", {}).keys())
            for s in all_serials:
                p = _serial_port(s)
                if p is not None:
                    port2serial[p] = s

            info("[OFFMON] 开始一轮掉线巡检…")

            # 收集本轮需要修复的任务（并发执行），仅在开始前全局点击一次 pause，全部完成后全局点击一次 continue
            jobs: list[tuple[int, Callable[[], None]]] = []  # (组号, 任务函数)

            for gi in range(1, 21):
                if should_stop():
                    break
                a_port, b_port = groups[gi]
                a_ser = port2serial.get(a_port)
                b_ser = port2serial.get(b_port)
                if not a_ser and not b_ser:
                    _logv(log, f"第{gi}组无在线设备，跳过", verbose)
                    continue

                # 判定是否掉线
                a_off = _exist(app, a_ser, paths["diaoxian"], thr) if a_ser else False
                b_off = _exist(app, b_ser, paths["diaoxian"], thr) if b_ser else False

                if not a_off and not b_off:
                    _logv(log, f"第{gi}组 A/B 均未掉线", verbose)
                    continue  # 情况3

                # 仅一台在线设备的特殊处理：
                # - 若该机器未掉线：通过
                # - 若检测到掉线：直接点击 diaoxian.png（纳入并发任务），不做 pause/continue（全局统一做）
                only_one = (a_ser is not None) ^ (b_ser is not None)
                if only_one:
                    single_ser = a_ser if a_ser else b_ser
                    single_off = a_off if a_ser else b_off
                    if not single_off:
                        _logv(log, f"第{gi}组：仅一台在线（{single_ser}），未检测到掉线，跳过", verbose)
                        continue
                    def _job_one(serial=single_ser, gi_=gi):
                        if should_stop():
                            return
                        info(f"[OFFMON] 第{gi_}组：仅一台在线且检测到掉线，在{_label(serial)}上直接点击 diaoxian")
                        _tap_img(app, serial, paths["diaoxian"], thr, log, name="diaoxian.png", wait_s=0.5, should_stop=should_stop)
                    jobs.append((gi, _job_one))
                    continue

                # 通用情形：构造该组的修复序列任务（选择 → confirm → diaoxian）
                def _make_job(gi_=gi, a_off_=a_off, b_off_=b_off, a_ser_=a_ser, b_ser_=b_ser):
                    def _job():
                        if should_stop():
                            return
                        # 选择执行在哪台：情况1在A；情况2在未掉线那台
                        target_for_select: Optional[str] = None
                        if a_off_ and b_off_:
                            target_for_select = a_ser_
                            info(f"[OFFMON] 第{gi_}组：A/B均掉线，在{_label(a_ser_)}上执行掉线选人")
                        else:
                            if a_off_ and b_ser_:
                                target_for_select = b_ser_
                                info(f"[OFFMON] 第{gi_}组：A掉线B正常，在{_label(b_ser_)}上执行掉线选人")
                            elif b_off_ and a_ser_:
                                target_for_select = a_ser_
                                info(f"[OFFMON] 第{gi_}组：B掉线A正常，在{_label(a_ser_)}上执行掉线选人")
                        if target_for_select and not should_stop():
                            _drop_line_selection(app, target_for_select, log, thr, verbose, should_stop)
                        if should_stop():
                            return
                        # confirm 目标：情况1 A；情况2 未掉线那台
                        target_for_confirm: Optional[str] = None
                        if a_off_ and b_off_:
                            target_for_confirm = a_ser_
                        else:
                            if a_off_:
                                target_for_confirm = b_ser_
                            elif b_off_:
                                target_for_confirm = a_ser_
                        if target_for_confirm and not should_stop():
                            info(f"[OFFMON] aaaaaaaaaaaaaaaaaaaaaaaaaaa开始在{_label(target_for_confirm)}上执行 confirm")
                            _tap_img(app, target_for_confirm, paths["confirm"], thr, log, name="confirm.png", wait_s=0.5, should_stop=should_stop)
                        if should_stop():
                            return
                        # diaoxian 目标：情况1 B；情况2 掉线那台
                        target_for_diaoxian: Optional[str] = None
                        if a_off_ and b_off_:
                            target_for_diaoxian = b_ser_
                        else:
                            target_for_diaoxian = a_ser_ if a_off_ else b_ser_ if b_off_ else None
                        if target_for_diaoxian and not should_stop():
                            info(f"[OFFMON] 开始在{_label(target_for_diaoxian)}上执行 diaoxian")
                            _tap_img(app, target_for_diaoxian, paths["diaoxian"], thr, log, name="diaoxian.png", wait_s=0.5, should_stop=should_stop)
                    return _job
                jobs.append((gi, _make_job()))

            # 若无任务，直接进入下轮等待
            if not jobs:
                total = max(1, int(interval_minutes)) * 60
                info(f"[OFFMON] 本轮无修复任务，等待 {total} 秒后进入下一轮…（可停止）")
                for _ in range(total):
                    if should_stop():
                        break
                    time.sleep(1.0)
                continue

            # 全局一次 pause（首次决定日志聚焦到“主日志”）
            # 离线监控修复开始：无条件暂停其他所有任务
            try:
                if hasattr(app, "_suspend_all_tasks_for_offmon"):
                    app._suspend_all_tasks_for_offmon()
            except Exception:
                pass

            try:
                if hasattr(app, "_select_log_tab"):
                    app._select_log_tab("main")
            except Exception:
                pass
            _activate_window_and_click("pause.png", log, title_keyword="护肝神器", should_stop=should_stop)
            if _sleep_until(should_stop, 10.0):
                break

            # 并发执行各组修复
            info(f"[OFFMON] 本轮需修复 {len(jobs)} 组，开始并发处理…")
            with futures.ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
                futs = [ex.submit(job) for _, job in jobs]
                for f in futs:
                    try:
                        f.result()
                    except Exception as e:
                        log(f"[OFFMON] 某组修复异常：{e}")
                    if should_stop():
                        break

            if should_stop():
                break
            # 全局一次 continue（前置 10 秒等待）；结束时维持主日志聚焦，无需频繁切换
            if _sleep_until(should_stop, 10.0):
                break
            try:
                if hasattr(app, "_select_log_tab"):
                    app._select_log_tab("main")
            except Exception:
                pass
            _activate_window_and_click("continue.png", log, title_keyword="护肝神器", should_stop=should_stop)
            # 本轮修复结束：恢复之前暂停的任务
            try:
                if hasattr(app, "_resume_suspended_after_offmon"):
                    app._resume_suspended_after_offmon()
            except Exception:
                pass

            # 
            #   

            # 一轮结束，等待下轮
            total = max(1, int(interval_minutes)) * 60
            info(f"[OFFMON] 本轮结束，等待 {total} 秒后进入下一轮…（可停止）")
            # 可中断的等待
            for _ in range(total):
                if should_stop():
                    break
                time.sleep(1.0)
        except Exception as e:
            log(f"[OFFMON] 运行异常：{e}")
            if _sleep_until(should_stop, 2.0):
                break

    info("[OFFMON] 已停止")

