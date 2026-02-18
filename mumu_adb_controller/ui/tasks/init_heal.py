"""
初始化治疗功能 - 为刷全军做准备
"""
import os
import sys
import time
from ..helpers import matcher
from . import init_to_wild

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

# 坐标定义
COORD_WILD_ENTER = (640, 360)  # 进入野外的坐标
COORD_QUICK_SELECT = (122, 931)  # 快速选择坐标
COORD_HEAL_INPUT_1 = (541, 398)  # 伤兵输入坐标1
COORD_HEAL_INPUT_2 = (539, 543)  # 伤兵输入坐标2
COORD_HEAL_INPUT_3 = (539, 686)  # 伤兵输入坐标3
COORD_HEAL_BUTTON = (580, 931)  # 治疗按钮坐标
COORD_SHANGBING_RANGE = ((495, 890), (602, 1107))  # 伤兵图标搜索范围

# 图片文件
IMG_SHANGBING = ["shangbing_1.png", "shangbing_2.png", "shangbing_3.png"]
IMG_0_SHANGBING = "0_shangbing.png"
IMG_999_SHANGBING = "999_shangbing.png"


def _paths():
    """获取所有图片路径"""
    P = lambda n: res_path("pic", n)
    return {
        "shangbing_list": [P(n) for n in IMG_SHANGBING],
        "0_shangbing": P(IMG_0_SHANGBING),
        "999_shangbing": P(IMG_999_SHANGBING),
    }


def _screencap(app, serial):
    """获取截图"""
    ok, data = app.adb.screencap(serial)
    return data if ok and data else None


def _double_tap(app, serial, x, y, delay=0.12):
    """双击指定坐标"""
    import sys
    print(f"[DEBUG] _double_tap: 第1次点击 ({x}, {y})", file=sys.stderr, flush=True)
    app.adb.input_tap(serial, x, y)
    time.sleep(delay)
    print(f"[DEBUG] _double_tap: 第2次点击 ({x}, {y})", file=sys.stderr, flush=True)
    app.adb.input_tap(serial, x, y)
    time.sleep(0.15)


def _single_tap(app, serial, x, y):
    """单击指定坐标"""
    import sys
    print(f"[DEBUG] _single_tap: 点击 ({x}, {y})", file=sys.stderr, flush=True)
    app.adb.input_tap(serial, x, y)


def _double_tap_shangbing(app, serial, log):
    """在指定范围内双击伤兵图标"""
    png = _screencap(app, serial)
    if png is None:
        log("[INIT] ❌ 截图失败")
        return False

    paths = _paths()

    for idx, img_path in enumerate(paths["shangbing_list"], 1):
        img_name = os.path.basename(img_path)
        if not os.path.isfile(img_path):
            continue

        ok, pos = matcher.match_in_range(png, img_path, COORD_SHANGBING_RANGE, threshold=0.8)

        if ok:
            x, y = pos
            log(f"[INIT] ✓ 找到伤兵图标")
            _double_tap(app, serial, x, y)
            return True

    log("[INIT] ❌ 未找到伤兵图标")
    return False


def _quick_select_zero(app, serial, log):
    """点击3次快速选择，确保选择0个伤兵"""
    for i in range(3):
        _single_tap(app, serial, *COORD_QUICK_SELECT)
        time.sleep(0.5)

    # 验证是否选择了0个伤兵
    time.sleep(0.5)
    png = _screencap(app, serial)
    if png is None:
        log("[INIT] ❌ 验证截图失败")
        return False

    paths = _paths()
    if os.path.isfile(paths["0_shangbing"]):
        ok, _ = matcher.match_one(png, paths["0_shangbing"], threshold=0.8)
        if ok:
            log("[INIT] ✓ 已选择0个伤兵")
            return True

    log("[INIT] ⚠️  未能确认选择0个伤兵")
    return False


def _input_shangbing_count(app, serial, count, log):
    """输入伤兵数量"""
    paths = _paths()

    # 尝试在输入坐标1输入
    _single_tap(app, serial, *COORD_HEAL_INPUT_1)
    time.sleep(0.2)
    app.adb.input_text(serial, str(count))
    time.sleep(0.5)

    # 检查是否成功
    png = _screencap(app, serial)
    if png is not None and os.path.isfile(paths["999_shangbing"]):
        ok, _ = matcher.match_one(png, paths["999_shangbing"], threshold=0.8)
        if ok:
            log(f"[INIT] ✓ 已输入{count}个伤兵")
            return True

    # 如果失败，尝试输入坐标2
    _single_tap(app, serial, *COORD_HEAL_INPUT_2)
    time.sleep(0.2)
    app.adb.input_text(serial, str(count))
    time.sleep(0.2)

    # 清除坐标1的内容
    _single_tap(app, serial, *COORD_HEAL_INPUT_1)
    time.sleep(0.2)
    for i in range(6):
        app.adb.input_keyevent(serial, 67)  # KEYCODE_DEL = 67
    time.sleep(0.5)

    # 再次检查
    png = _screencap(app, serial)
    if png is not None and os.path.isfile(paths["999_shangbing"]):
        ok, _ = matcher.match_one(png, paths["999_shangbing"], threshold=0.8)
        if ok:
            log(f"[INIT] ✓ 已输入{count}个伤兵")
            return True

    # 如果仍然失败，尝试输入坐标3
    _single_tap(app, serial, *COORD_HEAL_INPUT_3)
    time.sleep(0.2)
    app.adb.input_text(serial, str(count))
    time.sleep(0.2)

    # 清除坐标2的内容
    _single_tap(app, serial, *COORD_HEAL_INPUT_2)
    time.sleep(0.2)
    for i in range(3):
        app.adb.input_keyevent(serial, 67)  # KEYCODE_DEL = 67
    time.sleep(0.5)

    # 最后检查
    png = _screencap(app, serial)
    if png is not None and os.path.isfile(paths["999_shangbing"]):
        ok, _ = matcher.match_one(png, paths["999_shangbing"], threshold=0.8)
        if ok:
            log(f"[INIT] ✓ 已输入{count}个伤兵")
            return True

    log(f"[INIT] ❌ 无法输入{count}个伤兵")
    return False


def run_init_heal(app, serial: str, heal_count: int, toast, log, should_stop=None):
    """
    初始化治疗流程

    步骤：
    1. 调用初始化到野外
    2. 在范围内双击伤兵图标
    3. 点击3次快速选择，确保选择0个伤兵
    4. 输入伤兵数量（999或333）
    5. 持续点击治疗按钮，每3秒检查一次伤兵是否存在
    """
    if should_stop is None:
        should_stop = lambda: False

    log("[INIT] 开始初始化治疗流程")

    # STEP 1: 调用初始化到野外
    log("[INIT] STEP 1: 初始化到野外")

    # 创建一个简单的日志函数用于 init_to_wild
    def wild_log(msg):
        log(f"[INIT] [野外] {msg}")

    # 创建一个简单的 toast 函数用于 init_to_wild
    def wild_toast(msg):
        log(f"[INIT] [野外] 提示: {msg}")

    # 调用初始化到野外函数
    init_to_wild.run_init_to_wild(app, serial, wild_toast, wild_log)

    time.sleep(2)
    log("[INIT] ✓ STEP 1 完成")

    # STEP 2: 双击伤兵图标
    log("[INIT] STEP 2: 双击伤兵图标")
    if not _double_tap_shangbing(app, serial, log):
        log("[INIT] ❌ STEP 2 失败")
        toast("初始化治疗失败：未找到伤兵图标")
        return False
    time.sleep(1)
    log("[INIT] ✓ STEP 2 完成")

    # STEP 3: 快速选择0个伤兵
    log("[INIT] STEP 3: 快速选择0个伤兵")
    if not _quick_select_zero(app, serial, log):
        log("[INIT] ⚠️  STEP 3 失败")
    time.sleep(1)
    log("[INIT] ✓ STEP 3 完成")

    # STEP 4: 输入伤兵数量
    log(f"[INIT] STEP 4: 输入{heal_count}个伤兵")
    if not _input_shangbing_count(app, serial, heal_count, log):
        log(f"[INIT] ❌ STEP 4 失败")
        toast(f"初始化治疗失败：无法输入{heal_count}个伤兵")
        return False
    time.sleep(1)
    log("[INIT] ✓ STEP 4 完成")

    # STEP 5: 持续点击治疗按钮，每3秒检查一次伤兵是否存在
    log("[INIT] STEP 5: 持续点击治疗按钮")

    last_check_time = time.time()
    click_count = 0
    consecutive_not_found = 0  # 连续未找到伤兵的次数

    while not should_stop():
        _single_tap(app, serial, *COORD_HEAL_BUTTON)
        click_count += 1

        # 每3秒检查一次伤兵是否存在
        if time.time() - last_check_time >= 3:
            # 在指定范围内查找伤兵图标
            png = _screencap(app, serial)
            if png is not None:
                found_shangbing = False
                paths = _paths()

                # 尝试匹配三个伤兵图标中的任意一个
                for img_path in paths["shangbing_list"]:
                    if not os.path.isfile(img_path):
                        continue

                    ok, pos = matcher.match_in_range(png, img_path, COORD_SHANGBING_RANGE, threshold=0.8)
                    if ok:
                        found_shangbing = True
                        consecutive_not_found = 0  # 重置计数器
                        break

                if not found_shangbing:
                    consecutive_not_found += 1

                    # 检查是否连续3次都没找到
                    if consecutive_not_found >= 3:
                        log(f"[INIT] ✓ 伤兵已全部治疗（点击{click_count}次）")
                        toast("初始化治疗完成")
                        return True  # 返回 True 表示正常完成

            last_check_time = time.time()

        time.sleep(0.1)

    log("[INIT] ⚠️  初始化治疗被中断")
    return False

