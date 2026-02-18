"""
新版智能选兵模块 - 快速响应版本
按用户指定逻辑实现简洁快速的智能选兵功能
"""

import os
import time
try:
    import cv2  # type: ignore
    _CV2_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore[assignment]
    _CV2_IMPORT_ERROR = exc

import numpy as np
try:
    import pytesseract  # type: ignore
    _PYTESSERACT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - optional dependency
    pytesseract = None  # type: ignore[assignment]
    _PYTESSERACT_IMPORT_ERROR = exc
from typing import Dict, List, Tuple, Optional
from ..ui.helpers import matcher


class NewTroopSelector:
    """新版智能选兵选择器 - 调试版本"""
    # 静态模板缓存，降低启动开销
    _TEMPLATE_CACHE: Dict[str, np.ndarray] = {}

    def __init__(self, device_worker, device_log):
        self.device_worker = device_worker
        self.device_log = device_log

        # 调试开关：关闭时仅输出关键日志
        self.debug_enabled = False
        # 开关：容量检查（默认禁用，绕过OCR与截图）
        self.capacity_check_enabled = False

        # 坐标定义
        self.coordinates = {
            # 最大化按钮偏移
            'max_button_offset': (565, 55),

            # OCR识别区域
            'ocr_area': {
                'x1': 84,
                'y1': 169,
                'x2': 300,
                'y2': 221
            },

            # 拖动坐标
            'drag_start': (64, 1073),
            'drag_end': (64, 680)
        }

        # 模板存储（实例视图，引用静态缓存）
        self.templates = {}

        # 已处理的图标位置（避免重复）
        self.processed_positions = set()

        # 拖动计数
        self.drag_count = 0

    def log(self, message: str, *, force: bool = False):
        """统一日志输出；关闭调试时仅保留关键提示"""
        if not (force or self.debug_enabled):
            return
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}"
        self.device_log(full_msg)
        if self.debug_enabled:
            print(full_msg)

        
    def load_templates(self) -> bool:
        """加载识别模板"""
        try:
            self.log("📂 加载模板...")

            # 获取模板路径
            try:
                from ..common.pathutil import res_path
                base_path = res_path('pic', 'troops')
            except ImportError:
                base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'pic', 'troops')

            templates_to_load = {
                'fast_choose': 'fast_choose.png',
                'reset_button': 'reset_button.png',
                'shield': 'shield_icon.png',
                'spear': 'spear_icon.png'
            }

            loaded = 0
            for name, filename in templates_to_load.items():
                # 先尝试静态缓存
                if name in NewTroopSelector._TEMPLATE_CACHE:
                    self.templates[name] = NewTroopSelector._TEMPLATE_CACHE[name]
                    h, w = self.templates[name].shape[:2]
                    self.log(f"✅ {name}: {w}x{h} 来自缓存")
                    loaded += 1
                    continue

                path = os.path.join(base_path, filename)
                if os.path.exists(path):
                    template = cv2.imread(path, cv2.IMREAD_COLOR)
                    if template is not None:
                        self.templates[name] = template
                        NewTroopSelector._TEMPLATE_CACHE[name] = template
                        h, w = template.shape[:2]
                        self.log(f"✅ {name}: {w}x{h} 已加载")
                        loaded += 1
                    else:
                        self.log(f"❌ {name}: 读取失败")
                else:
                    self.log(f"⚠️ {name}: 文件不存在 {path}")

            return loaded >= 3

        except Exception as e:
            self.log(f"❌ 模板加载异常: {e}")
            return False

    def get_screenshot(self) -> Optional[np.ndarray]:
        """获取当前屏幕截图"""
        try:
            ok, data = self.device_worker.adb.screencap(self.device_worker.serial)
            if ok and data:
                arr = np.frombuffer(data, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            self.log("❌ 截图失败")
            return None
        except Exception as e:
            self.log(f"❌ 截图异常: {e}")
            return None
    
    def find_icons(self, template_name: str, threshold: float = 0.85) -> List[Tuple[int, int, int, int]]:
        """查找图标，返回(x,y,w,h)列表"""
        if template_name not in self.templates:
            self.log(f"⚠️ 模板 {template_name} 未加载")
            return []
            
        screen = self.get_screenshot()
        if screen is None:
            return []
            
        template = self.templates[template_name]
        h, w = template.shape[:2]
        
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)
        
        icons = []
        for pt in zip(*locations[::-1]):
            x, y = pt
            icons.append((x, y, w, h))
            
        self.log(f"🔍 {template_name}: 找到 {len(icons)} 个匹配")
        return icons
    
    def click_at(self, x: int, y: int, description: str = ""):
        """点击指定坐标"""
        self.log(f"👆 点击 {description}: ({x}, {y})")
        self.device_worker.adb.input_tap(self.device_worker.serial, x, y)
    
    def drag_screen(self, start: Tuple[int, int], end: Tuple[int, int], duration: int = 500):
        """拖动屏幕"""
        self.log(f"👋 拖动: {start} -> {end}, 时长: {duration}ms")
        self.device_worker.adb.input_swipe(
            self.device_worker.serial,
            start[0], start[1],
            end[0], end[1],
            duration
        )
    
    def get_capacity_text(self) -> str:
        """获取容量文字"""
        start_time = time.time()
        self.log("🔍 开始获取容量文字...")
        
        try:
            if pytesseract is None:
                detail = f"，导入异常：{_PYTESSERACT_IMPORT_ERROR}" if _PYTESSERACT_IMPORT_ERROR else ""
                self.log(f"⚠️ 缺少 pytesseract 依赖，容量 OCR 被跳过{detail}", force=True)
                return ""

            screen = self.get_screenshot()
            if screen is None:
                self.log("❌ 截图失败，无法进行OCR")
                elapsed = int((time.time() - start_time) * 1000)
                self.log(f"⏱️ 获取容量文字耗时: {elapsed}ms - 截图失败")
                return ""
                
            # 截取OCR区域
            ocr_area = self.coordinates['ocr_area']
            self.log(f"📐 OCR区域坐标: x1={ocr_area['x1']}, y1={ocr_area['y1']}, x2={ocr_area['x2']}, y2={ocr_area['y2']}")
            
            roi = screen[ocr_area['y1']:ocr_area['y2'], ocr_area['x1']:ocr_area['x2']]
            
            # 保存OCR区域图像用于调试
            debug_time = time.strftime("%H%M%S")
            debug_path = os.path.join(os.path.dirname(__file__), "..", "..", "debug", f"ocr_debug_{debug_time}.png")
            os.makedirs(os.path.dirname(debug_path), exist_ok=True)
            cv2.imwrite(debug_path, roi)
            self.log(f"📸 OCR区域截图已保存: {debug_path}")
            
            # OCR识别
            self.log("🔍 开始OCR识别...")
            try:
                text = pytesseract.image_to_string(roi, config='--psm 7 -c tessedit_char_whitelist=0123456789/')
                text = text.strip()
                self.log(f"📝 OCR识别结果: '{text}'")
                elapsed = int((time.time() - start_time) * 1000)
                self.log(f"⏱️ 获取容量文字耗时: {elapsed}ms - 成功")
                return text
            except Exception as ocr_error:
                self.log(f"❌ OCR识别失败: {ocr_error}")
                self.log("💡 解决方案: 请安装tesseract-ocr")
                self.log("   Windows: 下载并安装 tesseract-ocr-w64-setup-5.3.3.20231005.exe")
                self.log("   或使用: choco install tesseract")
                elapsed = int((time.time() - start_time) * 1000)
                self.log(f"⏱️ 获取容量文字耗时: {elapsed}ms - OCR失败")
                return ""
            
        except Exception as e:
            self.log(f"❌ 获取容量文字异常: {e}")
            elapsed = int((time.time() - start_time) * 1000)
            self.log(f"⏱️ 获取容量文字耗时: {elapsed}ms - 异常")
            return ""
    
    def is_capacity_full(self) -> bool:
        """检查容量是否已满 - 已按要求绕过OCR与截图，直接返回未满"""
        if not self.capacity_check_enabled:
            self.log("⏭️ 容量检查已禁用（跳过OCR与截图）")
            return False

        # 如需启用，请将 capacity_check_enabled 设为 True，并恢复下方代码
        start_time = time.time()
        text = self.get_capacity_text()
        if not text or '/' not in text:
            self.log("⚠️ 无法识别容量文字，跳过容量检查")
            elapsed = int((time.time() - start_time) * 1000)
            self.log(f"⏱️ 容量检查耗时: {elapsed}ms")
            return False
        try:
            parts = text.split('/')
            if len(parts) == 2:
                selected = int(parts[0].strip())
                total = int(parts[1].strip())
                is_full = selected == total
                elapsed = int((time.time() - start_time) * 1000)
                self.log(f"📊 容量检查结果: {selected}/{total} {'已满' if is_full else '未满'}, 耗时: {elapsed}ms")
                return is_full
        except ValueError:
            self.log("❌ 容量解析失败")
        elapsed = int((time.time() - start_time) * 1000)
        self.log(f"⏱️ 容量检查耗时: {elapsed}ms")
        return False

    def step1_check_fast_choose(self):
        """第一步：检查并点击快速选择按钮"""
        self.log("🚀 第一步：检查快速选择按钮...")
        step_start = time.time()
        icons = self.find_icons('fast_choose')

        if icons:
            x, y, w, h = icons[0]
            self.log(f"✅ 快速选择按钮已找到，坐标=({x},{y})，尺寸={w}x{h}")
            click_x = x + w // 2
            click_y = y + h // 2
            click_start = time.time()
            self.click_at(click_x, click_y, "快速选择")
            click_elapsed = int((time.time() - click_start) * 1000)
            self.log(f"⏱️ 点击耗时: {click_elapsed}ms")
            wait_ms = 100
            self.log(f"⏳ 等待界面响应: {wait_ms}ms")
            time.sleep(wait_ms / 1000.0)
            step_elapsed = int((time.time() - step_start) * 1000)
            self.log(f"🧾 第一步完成：已点击快速选择，总耗时: {step_elapsed}ms")
            return True
        else:
            step_elapsed = int((time.time() - step_start) * 1000)
            self.log(f"ℹ️ 未发现快速选择按钮，跳过（耗时: {step_elapsed}ms）")
            return False

    def step2_reset_all(self):
        """第二步：点击全部撤回"""
        self.log("🚀 第二步：点击全部撤回...")
        step_start = time.time()
        icons = self.find_icons('reset_button')

        if icons:
            x, y, w, h = icons[0]
            self.log(f"✅ 撤回按钮已找到，坐标=({x},{y})，尺寸={w}x{h}")
            click_x = x + w // 2
            click_y = y + h // 2
            click_start = time.time()
            self.click_at(click_x, click_y, "全部撤回")
            click_elapsed = int((time.time() - click_start) * 1000)
            self.log(f"⏱️ 点击耗时: {click_elapsed}ms")
            wait_ms = 100
            self.log(f"⏳ 等待界面响应: {wait_ms}ms")
            time.sleep(wait_ms / 1000.0)
            step_elapsed = int((time.time() - step_start) * 1000)
            self.log(f"🧾 第二步完成：已点击全部撤回，总耗时: {step_elapsed}ms")
            return True
        else:
            step_elapsed = int((time.time() - step_start) * 1000)
            self.log(f"❌ 未找到全部撤回按钮（耗时: {step_elapsed}ms）")
            return False

    def process_troop_type(self, troop_type: str) -> int:
        """处理特定类型的士兵
        Args:
            troop_type: 'shield' 或 'spear'
        Returns:
            处理的图标数量
        """
        self.log(f"🎯 开始处理{troop_type}兵")
        start_time = time.time()
        icons = self.find_icons(troop_type)

        processed = 0
        for x, y, w, h in icons:
            # 检查是否已处理过此位置（避免重复）
            pos_key = f"{troop_type}_{x}_{y}"
            if pos_key in self.processed_positions:
                self.log(f"⏭️ {troop_type}图标已处理过: ({x}, {y})")
                continue

            # 点击最大化按钮
            offset_x, offset_y = self.coordinates['max_button_offset']
            click_x = x + offset_x
            click_y = y + offset_y

            self.log(f"📍 {troop_type}图标位置: ({x}, {y}), 尺寸: {w}x{h}, 最大化按钮偏移: ({offset_x}, {offset_y}), 点击位置: ({click_x}, {click_y})")
            click_start = time.time()
            self.click_at(click_x, click_y, f"{troop_type}最大化")
            click_elapsed = int((time.time() - click_start) * 1000)
            self.log(f"⏱️ 点击耗时: {click_elapsed}ms")

            wait_ms = 100
            self.log(f"⏳ 等待界面响应: {wait_ms}ms")
            time.sleep(wait_ms / 1000.0)

            # 标记为已处理
            self.processed_positions.add(pos_key)
            processed += 1
            self.log(f"✅ 已处理{troop_type}图标: ({x}, {y})")

            # 检查容量是否已满
            if self.is_capacity_full():
                self.log("✅ 容量已满，流程结束")
                elapsed = int((time.time() - start_time) * 1000)
                self.log(f"⏱️ {troop_type}处理完成，耗时: {elapsed}ms")
                return processed

        elapsed = int((time.time() - start_time) * 1000)
        self.log(f"📊 处理了 {processed} 个{troop_type}兵图标，耗时: {elapsed}ms")
        return processed

    def step3_process_shields(self) -> bool:
        """第三步：处理盾兵"""
        self.log("🎯 步骤3: 处理盾兵")
        processed = self.process_troop_type('shield')
        return processed > 0
    
    def step4_process_spears(self) -> bool:
        """第四步：处理矛兵"""
        self.log("🎯 步骤4: 处理矛兵")
        processed = self.process_troop_type('spear')
        return processed > 0
    
    def step5_drag_and_search(self):
        """第五步：拖动士兵栏并继续搜索"""
        self.log(f"🎯 步骤5: 拖动士兵栏 (第{self.drag_count + 1}次)")
        start_time = time.time()
        
        if self.drag_count >= 2:
            self.log("⏹️ 已达到最大拖动次数，任务结束")
            return False
            
        # 执行拖动
        drag_start = self.coordinates['drag_start']
        drag_end = self.coordinates['drag_end']
        self.log(f"📍 拖动起始: {drag_start}, 拖动结束: {drag_end}")
        
        self.drag_screen(drag_start, drag_end)
        
        self.drag_count += 1
        wait_time = 500
        self.log(f"⏳ 等待界面稳定: {wait_time}ms")
        time.sleep(wait_time / 1000.0)
        
        elapsed = int((time.time() - start_time) * 1000)
        self.log(f"✅ 步骤5完成，当前拖动计数: {self.drag_count}, 耗时: {elapsed}ms")
        return True
    
    def run_troop_selection(self):
        """执行完整的智能选兵流程 - 调试版本"""
        self.log("智能选兵开始", force=True)
        
        # 重置状态
        self.processed_positions.clear()
        self.drag_count = 0
        
        # 加载模板
        if not self.load_templates():
            self.log("模板加载失败，已终止智能选兵", force=True)
            return False
        
        try:
            # 第一步：检查快速选择按钮
            self.log("📋 第一步：检查快速选择按钮")
            self.step1_check_fast_choose()
            
            # 第二步：点击全部撤回
            self.log("📋 第二步：点击全部撤回")
            if not self.step2_reset_all():
                self.log("无法找到全部撤回按钮", force=True)
                return False
            
            # 主循环：固定执行“初始 + 2次拖动”的三轮扫描（容量检查禁用时）
            self.log("🧭 策略：容量检查已禁用，将执行 初始页面 + 向上拖动2次 的全量扫描")
            total_rounds = 3  # 0=初始页面，1&2=拖动后页面
            for round_idx in range(total_rounds):
                round_start_time = time.time()

                # 拖动（第1、2轮）
                if round_idx > 0:
                    if self.drag_count >= 2:
                        self.log(f"⏹️ 已达到最大拖动次数 ({self.drag_count})，结束扫描")
                        break
                    self.log(f"📋 第五步：第{self.drag_count + 1}次拖动士兵栏（round={round_idx}）")
                    self.drag_screen(
                        self.coordinates['drag_start'],
                        self.coordinates['drag_end']
                    )
                    self.drag_count += 1
                    wait_time = 500
                    self.log(f"⏳ 等待拖动后界面稳定: {wait_time}ms")
                    time.sleep(wait_time / 1000.0)

                self.log(f"🔄 开始第 {round_idx + 1}/{total_rounds} 轮扫描")

                # 第三步：处理盾兵（本轮）
                self.log("📋 第三步：处理盾兵")
                _ = self.process_troop_type('shield')

                # 第四步：处理矛兵（本轮）
                self.log("📋 第四步：处理矛兵")
                _ = self.process_troop_type('spear')

                elapsed = int((time.time() - round_start_time) * 1000)
                self.log(f"⏱️ 本轮扫描结束（round={round_idx}），耗时: {elapsed}ms")

            self.log("智能选兵完成", force=True)
            return True

        except Exception as e:
            self.log(f"智能选兵出现异常: {e}", force=True)
            return False


def run_new_troop_selection(device_worker, device_log):
    """供外部调用的智能选兵函数
    
    Args:
        device_worker: 设备工作器实例
        device_log: 日志输出函数
    
    Returns:
        bool: 是否成功完成
    """
    if cv2 is None:
        base_msg = '\u7f3a\u5c11 opencv-python \u4f9d\u8d56\uff0c\u5df2\u8df3\u8fc7\u667a\u80fd\u9009\u5175\u4efb\u52a1\u3002\u8bf7\u5148\u6267\u884c\uff1apip install opencv-python'
        detail = f'\uff08\u5bfc\u5165\u5f02\u5e38\uff1a{_CV2_IMPORT_ERROR}\uff09' if _CV2_IMPORT_ERROR else ''
        message = f"{base_msg}{detail}"
        if callable(device_log):
            try:
                device_log(message)
            except Exception:
                print(message)
        else:
            print(message)
        return False

    selector = NewTroopSelector(device_worker, device_log)
    return selector.run_troop_selection()
