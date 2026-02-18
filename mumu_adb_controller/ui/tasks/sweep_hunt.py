# mumu_adb_controller/ui/tasks/sweep_hunt.py
import os
import sys
import time
from ..helpers import matcher
from .init_to_wild import run_init_to_wild

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

def _logv(log, msg: str, verbose: bool):
    if verbose:
        log(f"[DEBUG] {msg}")

# 坐标定义
# 野兽坐标
BEAST_30 = (439, 1053)
BEAST_26 = (395, 1049)
# 巨兽坐标
MONSTER_8 = (439, 1053)
MONSTER_7 = (356, 1052)
MONSTER_6 = (205, 1045)
MONSTER_5 = (131, 1053)
# 编队坐标
TEAM_POS = {
    1: (68, 121),
    2: (140, 129),
    3: (217, 123),
    4: (287, 120),
    5: (356, 120),
    6: (428, 123),
    7: (501, 132),
    8: (579, 125),
}

# 图片名
IMG_SHOUCANG = "shoucang.png"
IMG_DAIBAN   = "daiban.png"
IMG_XINGJUN  = "xingjun.png"
IMG_SEARCH   = "search.png"
IMG_WILD     = "wild_animal.png"
IMG_MONSTER  = "huge_monster.png"
IMG_SEARCH_CHAR = "serch_charactor.png"  # 兼容你的文件命名
IMG_attack = "attack.png"
IMG_JIJIE    = "jijie.png"
IMG_FAQI     = "faqijijie.png"
IMG_DELETE   = "delete_hero.png"
IMG_CHUZHENG = "chuzheng.png"
IMG_USE      = "use.png"

DEFAULT_STEP_DELAY = 0.30
SEARCH_DELAY = 1  # 搜索后延时

def _paths():
    P = lambda n: res_path("pic", n)
    return {
        "shoucang": P(IMG_SHOUCANG),
        "daiban":   P(IMG_DAIBAN),
        "xingjun":  P(IMG_XINGJUN),
        "search":   P(IMG_SEARCH),
        "wild":     P(IMG_WILD),
        "monster":  P(IMG_MONSTER),
        "search_char": P(IMG_SEARCH_CHAR),
        "attack": P(IMG_attack),
        "jijie":    P(IMG_JIJIE),
        "faqijijie":P(IMG_FAQI),
        "delete":   P(IMG_DELETE),
        "chuzheng": P(IMG_CHUZHENG),
        "use":      P(IMG_USE),
    }

def _screencap(app, serial):
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None

def _sleep_pause(app, sec: float):
    end = time.time() + max(0.0, float(sec))
    pause_ev = getattr(app, "pause_event", None)
    while time.time() < end:
        while pause_ev is not None and pause_ev.is_set():
            time.sleep(0.05)
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(0.1, remaining))

def _delay(app, step_delay: float):
    _sleep_pause(app, step_delay)

def _tap(app, serial, x, y):
    app.adb.input_tap(serial, x, y)

def _match_one(png_bytes, img_path, threshold=None):
    return matcher.match_one(png_bytes, img_path, threshold=matcher.THRESH if threshold is None else threshold)

def _exist(png_bytes, img_path, threshold) -> bool:
    ok, _ = matcher.match_one(png_bytes, img_path, threshold=threshold)
    return bool(ok)

def _ensure_wild(app, serial, log, paths, should_stop, step_delay: float, threshold, verbose) -> bool:
    """检测是否在野外；若不在，静默调用回到野外（不弹窗）"""
    if should_stop():
        return False
    png = _screencap(app, serial)
    if png is None:
        log("[HUNT] 无法截图，终止")
        return False
    in_wild = (
        _exist(png, paths["shoucang"], threshold)
        and _exist(png, paths["daiban"], threshold)
        and _exist(png, paths["xingjun"], threshold)
    )
    _logv(log, f"in_wild={in_wild} thr={threshold}", verbose)
    log(f"[STEP 1] 检测是否在野外：{'是' if in_wild else '否'}")
    if not in_wild:
        log("[STEP 1] 不在野外 → 静默初始化到野外")
        def _noop(_): pass
        run_init_to_wild(app, serial, toast=_noop, log=log, threshold=threshold, verbose=verbose)
        _sleep_pause(app, 0.8)
    _delay(app, step_delay)
    return True

def _tap_if_found(app, serial, img_path, log, step_name, threshold, verbose):
    png = _screencap(app, serial)
    if png is None:
        log(f"[{step_name}] 截图失败")
        return False, (0, 0)
    ok, (x, y) = _match_one(png, img_path, threshold=threshold)
    _logv(log, f"{step_name}: match {os.path.basename(img_path)} -> {ok}, pos=({x},{y})", verbose)
    if ok:
        _tap(app, serial, x, y)
        log(f"[{step_name}] 点击成功，坐标=({x},{y})")
        return True, (x, y)
    else:
        log(f"[{step_name}] 未找到 {os.path.basename(img_path)}")
        return False, (0, 0)

def _level_coord(hunt_type: str, level: int) -> tuple[int, int] | None:
    if hunt_type == "beast":
        return BEAST_30 if level == 30 else BEAST_26 if level == 26 else None
    else:
        return {
            8: MONSTER_8,
            7: MONSTER_7,
            6: MONSTER_6,
            5: MONSTER_5
        }.get(level)

def _single_cycle(app, serial, hunt_type: str, beast_levels: list, monster_levels: list,
                  teams: list, log, paths, should_stop, step_delay: float, threshold, verbose,
                  idx_beast: list, idx_monster: list, idx_team: list):
    """
    执行一次打野循环
    """
    if should_stop():
        return

    # 1) 野外
    if not _ensure_wild(app, serial, log, paths, should_stop, step_delay, threshold, verbose):
        log("[HUNT] 回到野外失败，跳过本次循环")
        return

    # 2) 搜索
    ok, _ = _tap_if_found(app, serial, paths["search"], log, "STEP 2", threshold, verbose)
    if not ok: return
    _sleep_pause(app, SEARCH_DELAY)
    _delay(app, step_delay)

    # 3) 选择类型
    if hunt_type == "beast" and beast_levels:
        ok, _ = _tap_if_found(app, serial, paths["wild"], log, "STEP 3", threshold, verbose)
        if not ok: return
    elif hunt_type == "monster" and monster_levels:
        ok, _ = _tap_if_found(app, serial, paths["monster"], log, "STEP 3", threshold, verbose)
        if not ok: return
    else:
        log("[STEP 3] 未选择有效类型/级别，跳过本次循环")
        return
    _delay(app, step_delay)

    # 4) 点击级别坐标（按多选轮询）
    if hunt_type == "beast":
        i = idx_beast[0]; level = beast_levels[i]; idx_beast[0] = (i + 1) % len(beast_levels)
    else:
        i = idx_monster[0]; level = monster_levels[i]; idx_monster[0] = (i + 1) % len(monster_levels)
    coord = _level_coord(hunt_type, level)
    if coord is None:
        log(f"[STEP 4] 未知级别：{level}，跳过")
        return
    log(f"[STEP 4] 点击 {('野兽' if hunt_type=='beast' else '巨兽')}{level}级 坐标 {coord}")
    _tap(app, serial, *coord)
    _delay(app, step_delay)

    # 5) 搜索角色
    ok, _ = _tap_if_found(app, serial, paths["search_char"], log, "STEP 5", threshold, verbose)
    if not ok: return
    _sleep_pause(app, SEARCH_DELAY)
    _delay(app, step_delay)

    # 6) 细分动作
    if hunt_type == "beast":
        ok, _ = _tap_if_found(app, serial, paths["attack"], log, "STEP 6", threshold, verbose)
        if not ok: return
    else:
        ok, _ = _tap_if_found(app, serial, paths["jijie"], log, "STEP 6-1", threshold, verbose)
        if not ok: return
        _delay(app, step_delay)
        ok, _ = _tap_if_found(app, serial, paths["faqijijie"], log, "STEP 6-2", threshold, verbose)
        if not ok: return
    _delay(app, step_delay)

    # 7) 编队（按多选轮询）
    j = idx_team[0]; team = teams[j]; idx_team[0] = (j + 1) % len(teams)
    pos = TEAM_POS.get(team)
    if not pos:
        log(f"[STEP 7] 未知编队：{team}，跳过")
        return
    log(f"[STEP 7] 点击编队{team} 坐标 {pos}")
    _tap(app, serial, *pos)
    _delay(app, step_delay)

    # 8) 是否出现"移除/替换武将"之类校验（delete_hero.png）
    # 先等待1秒让界面稳定
    log("[STEP 8] 等待1秒让界面稳定...")
    _sleep_pause(app, 1.0)

    png = _screencap(app, serial)
    if png is None:
        log("[STEP 8] 截图失败，跳过本轮")
        return
    exists = _exist(png, paths["delete"], threshold)
    _logv(log, f"STEP 8: delete_hero exists={exists}", verbose)
    if  exists:
        log("[STEP 8] 未出现 delete_hero.png → 说明没有英雄，跳出本次循环")
        log("[STEP 8] 等待3秒后进行下一循环...")
        _sleep_pause(app, 3.0)
        return

    # 9) 出征
    ok, _ = _tap_if_found(app, serial, paths["chuzheng"], log, "STEP 9", threshold, verbose)
    if ok:
        log("[STEP 9] 本轮循环结束")
    _delay(app, step_delay)

def _check_and_use_can(app, serial, paths, log, step_delay: float, threshold, verbose, 
                      used_cans: list, max_cans: int, should_stop) -> bool:
    """检测并使用体力罐头，返回是否继续执行"""
    if should_stop():
        return False
    
    png = _screencap(app, serial)
    if png is None:
        log("[CAN] 截图失败")
        return True
    
    exists = _exist(png, paths["use"], threshold)
    _logv(log, f"CAN: use.png exists={exists}, used={used_cans[0]}, max={max_cans}", verbose)
    
    if exists:
        # 计算剩余可用罐头数量
        remaining_cans = max_cans - used_cans[0]
        if remaining_cans <= 0:
            log(f"[CAN] 体力罐头已达上限 {max_cans}，结束打野")
            return False
        
        # 检查剩余罐头数量是否大于0，如果是则自动使用
        if remaining_cans > 0:
            log(f"[CAN] 检测到体力罐头界面，剩余可用罐头: {remaining_cans}")
            log(f"[CAN] 自动使用3个罐头...")
            
            # 点击3次使用罐头
            for click_count in range(3):
                if should_stop():
                    return False
                ok, (x, y) = _tap_if_found(app, serial, paths["use"], log, f"CAN-{click_count+1}", threshold, verbose)
                if ok:
                    _delay(app, step_delay)
                else:
                    log(f"[CAN] 第{click_count+1}次点击失败")
                    break
            
            used_cans[0] += 3
            log(f"[CAN] 使用3个罐头，已使用 {used_cans[0]}/{max_cans}")
            _delay(app, step_delay)

            # 罐头使用后发送返回键
            log("[CAN] 发送返回键退出罐头界面")
            app.adb.input_keyevent(serial, "KEYCODE_BACK")
            _delay(app, step_delay)

            # 重新点击chuzheng.png进入下一轮循环
            log("[CAN] 重新点击出征按钮")
            ok, _ = _tap_if_found(app, serial, paths["chuzheng"], log, "CAN-CHUZHENG", threshold, verbose)
            if ok:
                log("[CAN] 出征成功，进入下一轮循环")
            else:
                log("[CAN] 出征失败，可能不在正确界面")
    
    return True

def run_sweep_hunt(app, serial: str, hunt_type: str,
                   beast_levels: list | None = None,
                   monster_levels: list | None = None,
                   teams: list | None = None,
                   # 兼容旧参数名（device_tab.py 里曾传 selected_teams）
                   selected_teams: list | None = None,
                   can_count: int = 0,
                   toast=None, log=None, loop_count: int = 1,
                   should_stop=None, step_delay: float = DEFAULT_STEP_DELAY,
                   threshold: float | None = None, verbose: bool = False):
    """
    打野主流程
      - hunt_type: "beast" 野兽 / "monster" 巨兽
      - beast_levels: 野兽级别列表 [30, 26]，可多选（轮询）
      - monster_levels: 巨兽级别列表 [8, 7, 6, 5]，可多选（轮询）
      - teams / selected_teams: 编队列表 [1..8]，可多选（轮询）
      - can_count: 体力罐头数量，默认0（不使用）
      - loop_count: 循环次数
      - step_delay: 步与步之间的间隔
      - threshold: 匹配阈值（None 用默认）
      - verbose: 详细日志
    """
    if should_stop is None:
        should_stop = lambda: False
    if log is None:
        log = print

    thr = matcher.THRESH if threshold is None else float(threshold)
    paths = _paths()

    beast_levels = list(beast_levels or [])
    monster_levels = list(monster_levels or [])
    teams = list(teams or selected_teams or [])
    max_cans = max(0, int(can_count))
    used_cans = [0]  # 使用列表来传递引用

    # 校验
    if hunt_type == "beast" and not beast_levels:
        log("[HUNT] 参数错误：选择了野兽但未勾选任何级别"); return
    if hunt_type == "monster" and not monster_levels:
        log("[HUNT] 参数错误：选择了巨兽但未勾选任何级别"); return
    if not teams:
        log("[HUNT] 参数错误：未选择编队"); return

    log(f"[HUNT] 开始打野，体力罐头限制：{max_cans}")

    # 轮询索引
    idx_beast   = [0]
    idx_monster = [0]
    idx_team    = [0]

    n = max(1, int(loop_count))
    for i in range(1, n + 1):
        if should_stop():
            log("[HUNT] 停止指令收到，退出…")
            return
        
        # 检查罐头使用情况
        if not _check_and_use_can(app, serial, paths, log, step_delay, thr, verbose, used_cans, max_cans, should_stop):
            log("[HUNT] 体力罐头已达上限，结束打野")
            return

        log(f"[HUNT] 循环 {i}/{n} 开始（类型：{'野兽' if hunt_type=='beast' else '巨兽'}，已用罐头：{used_cans[0]}/{max_cans}）")
        _single_cycle(
            app, serial, hunt_type, beast_levels, monster_levels, teams,
            log, paths, should_stop, step_delay, thr, verbose,
            idx_beast, idx_monster, idx_team
        )
        log(f"[HUNT] 循环 {i}/{n} 结束 → 回到步骤1继续")

    log("[HUNT] 全部循环完成")
