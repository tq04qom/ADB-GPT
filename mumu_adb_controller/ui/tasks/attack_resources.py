# mumu_adb_controller/ui/tasks/attack_resources.py
import os, sys, time
from typing import Callable, Optional, List, Tuple
from ..helpers import matcher
from .init_to_wild import build_paths as build_init_paths

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
IMG_GOTO = P("goto.png")
IMG_GOTO_SEARCH = P("goto_search.png")
IMG_CHUZHENG_RED = P("chuzheng_red.png")
IMG_CHUZHENG_RED2 = P("chuzheng_red2.png")
IMG_CHUZHENG_BLUE_2 = P("chuzheng_blue_2.png")
IMG_FULL_QUEUE5 = P("full_queue5.png")
IMG_FULL_QUEUE6 = P("full_queue6.png")


def _sleep_check(should_stop: Callable[[], bool], seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if should_stop():
            return True
        time.sleep(min(0.1, end - time.time()))
    return False


def _sleep_check_pause(app, should_stop: Callable[[], bool], seconds: float) -> bool:
    """带全局暂停感知的 sleep：
    - 收到停止立即返回 True
    - 若处于全局暂停，则阻塞在此直到恢复或收到停止
    - 正常等待 seconds 后返回 False
    """
    end = time.time() + seconds
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        if should_stop():
            return True
        # 若处于全局暂停，阻塞直到恢复
        while pause_ev is not None and pause_ev.is_set():
            if should_stop():
                return True
            time.sleep(0.05)
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(0.1, remaining))
    return False


def _screencap(app, serial) -> Optional[bytes]:
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _tap(app, serial, x, y):
    app.adb.input_tap(serial, int(x), int(y))


def _tap_if_found(app, serial, img_path: str, log: Callable[[str], None], name: str, threshold: Optional[float] = None) -> bool:
    """截图→模板匹配→(可选)点击，并输出详细日志（包括分数/阈值/坐标）。"""
    png = _screencap(app, serial)
    if png is None:
        log(f"[{name}] 截图失败")
        return False
    thr = matcher.THRESH if threshold is None else float(threshold)
    ok, (x, y), score = matcher.match_one_detail(png, img_path, threshold=thr)
    base = os.path.basename(img_path)
    if ok:
        _tap(app, serial, x, y)
        log(f"[{name}] 命中 {base} score={score:.3f}>=thr={thr:.2f} → tap({x},{y})")
        return True
    else:
        log(f"[{name}] 未命中 {base} score={score:.3f}<thr={thr:.2f}，不点击")


def _tap_chuzheng_red(app, serial, log: Callable[[str], None], name: str, primary_threshold: Optional[float] = None) -> bool:
    """优先用 chuzheng_red.png（默认阈值=全局thr），不命中则回退 chuzheng_red2.png（阈值固定0.84）。
    输出详细日志，未命中也记录两个模板的得分。
    返回 True 表示已点击其一，False 表示均未命中。
    """
    thr1 = matcher.THRESH if primary_threshold is None else float(primary_threshold)
    thr2 = 0.84
    png = _screencap(app, serial)
    if png is None:
        log(f"[{name}] 截图失败")
        return False
    ok1, pos1, sc1 = matcher.match_one_detail(png, IMG_CHUZHENG_RED, threshold=thr1)
    if ok1:
        _tap(app, serial, pos1[0], pos1[1])
        log(f"[{name}] 命中 chuzheng_red.png score={sc1:.3f}>=thr={thr1:.2f} → tap({pos1[0]},{pos1[1]})")
        return True
    ok2, pos2, sc2 = matcher.match_one_detail(png, IMG_CHUZHENG_RED2, threshold=thr2)
    if ok2:
        _tap(app, serial, pos2[0], pos2[1])
        log(f"[{name}] 备选命中 chuzheng_red2.png score={sc2:.3f}>=thr={thr2:.2f} → tap({pos2[0]},{pos2[1]})")
        return True
    log(f"[{name}] 未命中 red({sc1:.3f}<thr={thr1:.2f}) & red2({sc2:.3f}<thr={thr2:.2f})，不点击")
    return False

def parse_coords_text(text: str) -> List[Tuple[int, int, str, int]]:
    """
    解析坐标文本：每行一个：x:y:备注名:攻击轮次
    返回列表 [(x, y, name, rounds), ...]
    """
    res = []
    for line in (text or '').splitlines():
        s = line.strip()
        if not s:
            continue
        parts = s.split(":")
        if len(parts) < 4:
            # 不足字段，跳过
            continue
        try:
            x = int(parts[0].strip())
            y = int(parts[1].strip())
            name = parts[2].strip()
            rounds = int(parts[3].strip())
            if rounds <= 0:
                rounds = 1
            res.append((x, y, name, rounds))
        except Exception:
            continue
    return res


def ensure_wild(app, serial: str, toast, log, threshold: Optional[float], verbose: bool) -> bool:
    """
    检测是否已处于野外三要素；若不在，则调用“初始化到野外”并每次等待3秒，重试最多3次。
    返回 True/False 表示最终是否在野外。
    """
    thr = matcher.THRESH if threshold is None else float(threshold)
    init_paths = build_init_paths()

    def check_wild_once() -> bool:
        png = _screencap(app, serial)
        if png is None:
            log("[WILD] 截图失败")
            return False
        return matcher.exist_all(png, init_paths, ["daiban", "xingjun", "shoucang"], threshold=thr)

    if check_wild_once():
        log("[WILD] 已处于野外初始化状态")
        return True

    # 最多3次调用初始化到野外
    from .init_to_wild import run_init_to_wild
    for i in range(1, 4):
        log(f"[WILD] 第{i}次尝试初始化到野外…")
        run_init_to_wild(app, serial, toast=toast, log=log, threshold=thr, verbose=verbose)
        if _sleep_check(lambda: False, 3.0):
            pass
        if check_wild_once():
            log("[WILD] 已进入野外初始化状态")
            return True
    log("[WILD] 3次仍未进入野外，放弃本轮坐标")
    return False


def wait_until_queue_clears(app, serial: str, log: Callable[[str], None], should_stop: Callable[[], bool],
                            roi: Tuple[int, int, int, int], interval_sec: float = 2.0,
                            threshold: float = 0.95) -> str:
    """
    返回状态："cleared"（目标消失/已归位）、"timeout"（超过最大等待时长）、"stopped"（收到停止信号）。
    逻辑：
    - 先在 ROI 内探测 full_queue6 或 full_queue5，若发现其一，则仅盯住该图重复检测；
    - 每 2 秒检测一次，最多等待 3 分钟；当目标图在 ROI 中消失，判定“军队归位”；
    - 若首次即未见任一图，直接认为已归位。
    """
    x1, y1, x2, y2 = roi
    max_wait_sec = 180.0
    start_ts = time.time()

    # 首次探测，确认要盯的目标
    target_img = None
    target_name = None
    while not should_stop():
        png = _screencap(app, serial)
        if png is None:
            log("[QUEUE] 首次检测截图失败，继续…")
        else:
            f6, p6 = matcher.match_in_range(png, IMG_FULL_QUEUE6, ((x1, y1), (x2, y2)), threshold=threshold)
            f5, p5 = matcher.match_in_range(png, IMG_FULL_QUEUE5, ((x1, y1), (x2, y2)), threshold=threshold)
            in6 = f6
            in5 = f5
            if in6 or in5:
                if in6:
                    target_img, target_name = IMG_FULL_QUEUE6, "full_queue6"
                    log(f"[QUEUE] 初次检测到 full_queue6 @{p6}，开始轮询…")
                else:
                    target_img, target_name = IMG_FULL_QUEUE5, "full_queue5"
                    log(f"[QUEUE] 初次检测到 full_queue5 @{p5}，开始轮询…")
                break
            else:
                log("[QUEUE] 初次未见队列满图，判定已归位")
                return "cleared"
        if time.time() - start_ts > max_wait_sec:
            log("[QUEUE] 首次探测超时（>180s），继续执行后续步骤")
            return "timeout"
        if _sleep_check_pause(app, should_stop, interval_sec):
            return "stopped"

    # 轮询直到目标消失
    while not should_stop():
        if time.time() - start_ts > max_wait_sec:
            log("[QUEUE] 等待队列归位超时（>180s）")
            return "timeout"
        png = _screencap(app, serial)
        if png is None:
            log("[QUEUE] 截图失败，继续等待…")
        else:
            found, pos = matcher.match_in_range(png, target_img, ((x1, y1), (x2, y2)), threshold=threshold)
            in_roi = found
            log(f"[QUEUE] 监测 {target_name}={in_roi}@{pos} roi=({x1},{y1})-({x2},{y2})")
            if not in_roi:
                log("[QUEUE] 目标图已消失，判定军队归位")
                return "cleared"
        if _sleep_check_pause(app, should_stop, interval_sec):
            return "stopped"
    return "stopped"


def run_attack_resources(app, serial: str,
                         coords: List[Tuple[int, int, str, int]],
                         toast: Callable[[str], None],
                         log: Callable[[str], None],
                         should_stop: Callable[[], bool],
                         threshold: Optional[float] = None,
                         verbose: bool = False,
                         on_timeout: str = "continue"):
    """
    危险操作：仅当前设备。坐标序列 [(x,y,name,rounds), ...]
    步骤：
      1) 回到野外（最多重试3次）
      2) 前往城镇并输入坐标 → goto
      3) 第1轮攻击：循环6次点击（359,558）→ 红出征 → 蓝出征
      4) 若还需更多轮：在 ROI 内等待 full_queue5/6 消失后，再次执行攻击轮
      5) 切换到下一个坐标，重复 1）-4）
    选项 on_timeout："continue"（继续本坐标）、"skip"（跳过本坐标）、"abort"（终止任务）
    """
    thr = matcher.THRESH if threshold is None else float(threshold)

    toast("开始打资源（危险操作）")
    log("[ATTACK] 启动：打资源（仅当前设备）")

    for idx, (x, y, name, rounds) in enumerate(coords, start=1):
        if should_stop():
            break
        log("=" * 48)
        log(f"[ATTACK] 第{idx}组：坐标=({x},{y}) 备注={name} 轮数={rounds}")

        # Step 1：回到野外
        if not ensure_wild(app, serial, toast, log, threshold=thr, verbose=verbose):
            log(f"[ATTACK] 坐标{name}：无法进入野外，跳过")
            continue

        # Step 3：前往城镇并输入坐标（加速与速度因子兼容）
        if should_stop():
            break
        # 读取速度因子（与其他任务一致：sec * speed）
        try:
            speed = float(getattr(app, "get_speed_factor", lambda: 1.0)())
        except Exception:
            speed = 1.0
        log(f"[STEP3] 速度因子 speed={speed:.2f}")
        def _wait(sec: float) -> bool:
            return _sleep_check(should_stop, max(0.0, sec) * speed)

        log("[STEP3] 点击(326,1064) 打开坐标面板")
        _tap(app, serial, 326, 1064)
        if _wait(0.25):  # 原 0.5
            break
        log("[STEP3] 点击(246,618) 聚焦 X 输入框")
        _tap(app, serial, 246, 618)
        if _wait(0.12):  # 原 0.2
            break
        for _ in range(5):
            if should_stop():
                break
            app.adb.input_keyevent(serial, 67)  # DEL
            if _wait(0.05):
                break
        log(f"[STEP3] 输入 X={x}")
        app.adb.input_text(serial, str(x))
        if _wait(0.12):  # 原 0.2
            break
        log("[STEP3] 点击(512,618) 聚焦 Y 输入框")
        _tap(app, serial, 512, 618)
        if _wait(0.12):  # 原 0.2
            break
        for _ in range(5):
            if should_stop():
                break
            app.adb.input_keyevent(serial, 67)
            if _wait(0.05):
                break
        log(f"[STEP3] 输入 Y={y}")
        app.adb.input_text(serial, str(y))
        if _wait(0.12):  # 原 0.2
            break
        # 点击 goto（tap_if_found 内含详细日志）
        _tap_if_found(app, serial, IMG_GOTO, log, "GOTO", threshold=thr)
        if _wait(0.15):  # 原 0.3
            break
        log("[STEP3] 点击(359,558) 展开目标信息面板")
        _tap(app, serial, 359, 558)
        if _wait(0.15):  # 原 0.3
            break

        # Step 4：第1轮攻击（固定6次）
        cur_round = 0
        log("[ROUND1] 开始第1轮（6次）")
        for i in range(6):
            if should_stop():
                break
            log(f"[ROUND1] {i+1}/6: 点空地(359,558)")
            _tap(app, serial, 359, 558)
            if _wait(0.15):  # 原 0.3
                break
            if _tap_chuzheng_red(app, serial, log, name=f"ROUND-red[{i+1}/6]", primary_threshold=thr):
                if _sleep_check_pause(app, should_stop, 0.2):
                    break
            if _wait(0.15):
                break
            _tap_if_found(app, serial, IMG_CHUZHENG_BLUE_2, log, f"ROUND-blue2[{i+1}/6]", threshold=thr)
            if _wait(0.15):
                break
        # 额外：本轮结束后等待0.2s（受速度因子影响）
        if _wait(0.2):
            break
        cur_round += 1
        # 额外：检查是否出现 goto_search.png，若出现则“本轮攻击结束”→ 发送返回键 → 等待0.2s
        try:
            png = _screencap(app, serial)
            if png is not None:
                found, pos, sc = matcher.match_one_detail(png, IMG_GOTO_SEARCH, threshold=thr)
                if found:
                    log(f"[ROUND1] 检测到 goto_search.png (score={sc:.3f}@{pos}) → 本轮攻击结束，发送返回键")
                    app.adb.input_back(serial)
                    if _wait(0.2):
                        break
                else:
                    log(f"[ROUND1] 未检测到 goto_search.png，继续后续流程")
            else:
                log("[ROUND1] 截图失败，跳过 goto_search 检查，继续后续流程")
        except Exception as e:
            log(f"[ROUND1] 检查 goto_search.png 时异常：{e}，继续后续流程")

        # Step 5：循环剩余轮数
        roi = (174, 181, 259, 233)
        while cur_round < rounds:
            log(f"[ATTACK] 等待队列清空…（第{cur_round}/{rounds}轮后）")
            res = wait_until_queue_clears(app, serial, log, should_stop, roi=roi, interval_sec=2.0, threshold=0.95)
            if res == "stopped":
                log("[ATTACK] 收到停止信号，终止本任务")
                return
            if res == "timeout":
                # 根据 on_timeout 选项处理
                if on_timeout == "skip":
                    log("[ATTACK] 等待超时：跳过本坐标，切换到下一组坐标")
                    break  # 跳到下一组坐标
                if on_timeout == "abort":
                    log("[ATTACK] 等待超时：终止本任务")
                    return
                # 默认 continue：继续下一轮攻击
                log("[ATTACK] 等待超时：继续本坐标执行下一轮攻击")
            # 再执行一轮攻击
            log(f"[ATTACK] 执行第{cur_round+1}轮攻击（6次点击）…")
            for i in range(6):
                if should_stop():
                    break
                log(f"[ROUND{cur_round+1}] {i+1}/6: 点空地(359,558)")
                _tap(app, serial, 359, 558)
                if _wait(0.15):
                    break
                if _tap_chuzheng_red(app, serial, log, name=f"ROUND-red[{cur_round+1}-{i+1}/6]", primary_threshold=thr):
                    if _sleep_check_pause(app, should_stop, 0.2):
                        break
                if _wait(0.15):
                    break
                _tap_if_found(app, serial, IMG_CHUZHENG_BLUE_2, log, f"ROUND-blue2[{cur_round+1}-{i+1}/6]", threshold=thr)
                if _wait(0.15):
                    break
            cur_round += 1

        # Step 6：在切换到下一个坐标前，确保最后一轮也已“军队归位”
        try:
            log("[ATTACK] 本坐标所有轮次完成，最后等待军队归位后再切换下一坐标…")
            roi = (174, 181, 259, 233)
            res_final = wait_until_queue_clears(app, serial, log, should_stop, roi=roi, interval_sec=2.0, threshold=0.95)
            if res_final == "stopped":
                log("[ATTACK] 收到停止信号，终止本任务"); return
            if res_final == "timeout":
                if on_timeout == "abort":
                    log("[ATTACK] 最终等待超时：终止本任务"); return
                # skip/continue：均继续到下一个坐标
                log("[ATTACK] 最终等待超时：继续切换到下一个坐标")
        except Exception as e:
            log(f"[ATTACK] 最终等待归位时发生异常：{e}")

    toast("打资源已结束")
    log("[ATTACK] 结束：打资源")

