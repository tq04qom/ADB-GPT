"""
移动端风格界面 - 纵向滚动布局
特点：
- 大字号、大按钮
- 纵向滚动排列
- 横向宽度压缩时整体缩放
- 保留设备标签页
- 无日志模块，仅供操作
"""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QGroupBox, QRadioButton, QGridLayout, QComboBox, QScrollArea, QTabWidget,
    QSizePolicy
)
from PySide6.QtGui import QFont

from ..common.logger import Logger
from ..common.worker import DeviceWorker
from ..core.adb import AdbClient

# 业务任务
from ..ui.tasks.sweep_army import run_sweep_army
from ..ui.tasks.sweep_city import run_sweep_city
from ..ui.tasks.sweep_fort import run_sweep_fort
from ..ui.tasks.auto_garrison import run_auto_garrison
from ..ui.tasks.emergency_heal import run_emergency_heal
from ..ui.tasks.init_to_wild import run_init_to_wild
from ..ui.tasks.withdraw_troops import run_withdraw_troops

# 导入扩展面板
from .panels.hunt_panel import HuntPanel
from .panels.bear_panel import BearPanel
from .panels.alliance_panel import AlliancePanel
from .panels.tools_panel import ToolsPanel
from .panels.resources_panel import ResourcesPanel


class _UiSignal(QObject):
    reset_button = Signal(object, str)  # (QPushButton, original_text)
    toast = Signal(str)


class MobileDeviceTab(QWidget):
    """移动端风格的设备标签页"""
    
    def __init__(self, app, serial: str):
        super().__init__(parent=app)
        self.app = app
        self.serial = serial
        self.logger: Logger = app.logger
        self.adb: AdbClient = app.adb
        self.worker: Optional[DeviceWorker] = app.workers.get(serial)
        
        self._sig = _UiSignal()
        self._sig.reset_button.connect(self._on_reset_button)
        self._sig.toast.connect(self._on_toast)
        
        self._running_tasks = set()
        
        # 基础字体大小（可根据窗口宽度缩放）
        self.base_font_size = 14
        
        self._build_ui()
        self.refresh_status()
    
    def _build_ui(self):
        """构建移动端风格UI"""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 设备标题（大字号）
        self.title_label = QLabel(f"📱 {self.serial}")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.title_label)

        # 功能标签页（与主界面一致）
        self.func_tabs = QTabWidget()
        tab_font = QFont()
        tab_font.setPointSize(14)
        self.func_tabs.setFont(tab_font)
        root.addWidget(self.func_tabs, 1)

        # 出征页
        self._build_outing_tab()

        # 驻军页
        self._build_garrison_tab()

        # 治疗页
        self._build_heal_tab()

        # 打野页
        self._build_hunt_tab()

        # 打熊页
        self._build_bear_tab()

        # 联盟页
        self._build_alliance_tab()

        # 打资源页
        self._build_resources_tab()

        # 工具页
        self._build_tools_tab()
    
    def _create_big_button(self, text: str, color: str = "#4CAF50") -> QPushButton:
        """创建大按钮"""
        btn = QPushButton(text)
        btn.setMinimumHeight(60)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        btn.setFont(font)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }}
            QPushButton:hover {{
                background-color: {self._darken_color(color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(color, 0.3)};
            }}
            QPushButton:disabled {{
                background-color: #CCCCCC;
                color: #666666;
            }}
        """)
        return btn
    
    def _darken_color(self, color: str, factor: float = 0.15) -> str:
        """使颜色变暗"""
        if color.startswith("#"):
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            r = int(r * (1 - factor))
            g = int(g * (1 - factor))
            b = int(b * (1 - factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        return color
    
    def _create_label(self, text: str, size: int = 14) -> QLabel:
        """创建标签"""
        label = QLabel(text)
        font = QFont()
        font.setPointSize(size)
        label.setFont(font)
        return label
    
    def _create_input(self, default: str = "", width: int = 100) -> QLineEdit:
        """创建输入框"""
        input_field = QLineEdit(default)
        input_field.setMinimumHeight(45)
        input_field.setMinimumWidth(width)
        font = QFont()
        font.setPointSize(14)
        input_field.setFont(font)
        return input_field
    
    def _build_outing_tab(self):
        """构建出征页"""
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)

        v = QVBoxLayout(page)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)

        # 出征+治疗分组
        box = QGroupBox("⚔️ 出征+治疗")
        box_font = QFont()
        box_font.setPointSize(16)
        box_font.setBold(True)
        box.setFont(box_font)
        v.addWidget(box)

        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        grid.setSpacing(10)
        
        # 任务类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(self._create_label("任务类型:", 14))
        self.mode_army = QRadioButton("刷全军")
        self.mode_city = QRadioButton("刷王城")
        self.mode_army.setChecked(True)
        for rb in [self.mode_army, self.mode_city]:
            rb_font = QFont()
            rb_font.setPointSize(14)
            rb.setFont(rb_font)
        self.mode_army.toggled.connect(self._update_outing_mode)
        type_layout.addWidget(self.mode_army)
        type_layout.addWidget(self.mode_city)
        type_layout.addStretch()
        v.addLayout(type_layout)
        
        # 刷全军参数
        self.army_panel = QWidget()
        army_layout = QVBoxLayout(self.army_panel)
        army_layout.setContentsMargins(0, 0, 0, 0)
        army_layout.setSpacing(10)
        
        army_row1 = QHBoxLayout()
        army_row1.addWidget(self._create_label("持续秒数:", 13))
        self.army_duration = self._create_input("300", 100)
        army_row1.addWidget(self.army_duration)
        army_row1.addStretch()
        army_layout.addLayout(army_row1)
        
        army_row2 = QHBoxLayout()
        army_row2.addWidget(self._create_label("治疗时长:", 13))
        self.army_heal_sec = self._create_input("8", 80)
        army_row2.addWidget(self.army_heal_sec)
        army_row2.addWidget(self._create_label("等待:", 13))
        self.army_wait_sec = self._create_input("0", 80)
        army_row2.addWidget(self.army_wait_sec)
        army_row2.addStretch()
        army_layout.addLayout(army_row2)
        
        v.addWidget(self.army_panel)
        
        # 刷王城参数
        self.city_panel = QWidget()
        city_layout = QVBoxLayout(self.city_panel)
        city_layout.setContentsMargins(0, 0, 0, 0)
        city_layout.setSpacing(10)
        
        city_row1 = QHBoxLayout()
        city_row1.addWidget(self._create_label("目标:", 13))
        self.city_target = QComboBox()
        self.city_target.addItems(["北地炮台", "西城炮台", "南翼炮台", "东城炮台", "太阳城"])
        self.city_target.setMinimumHeight(45)
        city_target_font = QFont()
        city_target_font.setPointSize(13)
        self.city_target.setFont(city_target_font)
        city_row1.addWidget(self.city_target, 1)
        city_layout.addLayout(city_row1)
        
        city_row2 = QHBoxLayout()
        self.city_queue_default = QRadioButton("默认队列")
        self.city_queue_12 = QRadioButton("1队+2队")
        self.city_queue_default.setChecked(True)
        for rb in [self.city_queue_default, self.city_queue_12]:
            rb_font = QFont()
            rb_font.setPointSize(13)
            rb.setFont(rb_font)
        city_row2.addWidget(self.city_queue_default)
        city_row2.addWidget(self.city_queue_12)
        city_row2.addStretch()
        city_layout.addLayout(city_row2)
        
        city_row3 = QHBoxLayout()
        city_row3.addWidget(self._create_label("治疗:", 13))
        self.city_heal_seconds = self._create_input("8", 70)
        city_row3.addWidget(self.city_heal_seconds)
        city_row3.addWidget(self._create_label("等待:", 13))
        self.city_wait_seconds = self._create_input("0", 70)
        city_row3.addWidget(self.city_wait_seconds)
        city_row3.addStretch()
        city_layout.addLayout(city_row3)
        
        v.addWidget(self.city_panel)
        self.city_panel.hide()
        
        # 开始按钮
        self.outing_btn = self._create_big_button("🚀 开始刷全军", "#2196F3")
        self.outing_btn.clicked.connect(self._btn_outing)
        v.addWidget(self.outing_btn)
        
        layout.addWidget(box)
    
    def _add_garrison_section(self, layout: QVBoxLayout):
        """自动驻军模块"""
        box = QGroupBox("🏰 自动驻军")
        box_font = QFont()
        box_font.setPointSize(16)
        box_font.setBold(True)
        box.setFont(box_font)
        
        v = QVBoxLayout(box)
        v.setSpacing(10)
        
        self.garrison_btn = self._create_big_button("▶️ 开始驻军", "#FF9800")
        self.garrison_btn.clicked.connect(self._btn_garrison)
        v.addWidget(self.garrison_btn)
        
        layout.addWidget(box)
    
    def _add_heal_section(self, layout: QVBoxLayout):
        """紧急治疗模块"""
        box = QGroupBox("💊 紧急治疗")
        box_font = QFont()
        box_font.setPointSize(16)
        box_font.setBold(True)
        box.setFont(box_font)
        
        v = QVBoxLayout(box)
        v.setSpacing(10)
        
        self.heal_btn = self._create_big_button("🚑 紧急治疗", "#F44336")
        self.heal_btn.clicked.connect(self._btn_heal)
        v.addWidget(self.heal_btn)
        
        layout.addWidget(box)
    
    def _add_tools_section(self, layout: QVBoxLayout):
        """工具模块"""
        box = QGroupBox("🔧 工具")
        box_font = QFont()
        box_font.setPointSize(16)
        box_font.setBold(True)
        box.setFont(box_font)
        
        v = QVBoxLayout(box)
        v.setSpacing(10)
        
        # 初始化到野外
        self.init_btn = self._create_big_button("🌲 初始化到野外", "#009688")
        self.init_btn.clicked.connect(self._btn_init_to_wild)
        v.addWidget(self.init_btn)
        
        # 一键撤军
        self.withdraw_btn = self._create_big_button("↩️ 一键撤军", "#9C27B0")
        self.withdraw_btn.clicked.connect(self._btn_withdraw)
        v.addWidget(self.withdraw_btn)
        
        layout.addWidget(box)

    # ============ 业务逻辑 ============

    def _update_outing_mode(self):
        """切换出征模式"""
        if self.mode_army.isChecked():
            self.army_panel.show()
            self.city_panel.hide()
            self.outing_btn.setText("🚀 开始刷全军")
        else:
            self.army_panel.hide()
            self.city_panel.show()
            self.outing_btn.setText("🚀 开始刷王城")

    def _btn_outing(self):
        """出征按钮"""
        if self.mode_army.isChecked():
            self._btn_sweep_army()
        else:
            self._btn_sweep_city()

    def _btn_sweep_army(self):
        """刷全军"""
        if "sweep_army" in self._running_tasks:
            self._toast("刷全军任务正在运行")
            return

        try:
            duration = int(self.army_duration.text() or "300")
            heal_sec = int(self.army_heal_sec.text() or "8")
            wait_sec = int(self.army_wait_sec.text() or "0")
        except ValueError:
            self._toast("参数错误：请输入有效数字")
            return

        def runner(should_stop):
            run_sweep_army(
                self.app, self.serial,
                duration_sec=duration,
                heal_seconds=heal_sec,
                wait_seconds=wait_sec,
                toast=self._toast,
                log=lambda m: None,  # 无日志
                should_stop=should_stop,
                threshold=None,
                verbose=False
            )

        self._start_task_with_button("sweep_army", runner, self.outing_btn, "🚀 开始刷全军")

    def _btn_sweep_city(self):
        """刷王城"""
        if "sweep_city" in self._running_tasks:
            self._toast("刷王城任务正在运行")
            return

        target_map = {
            "北地炮台": "north",
            "西城炮台": "west",
            "南翼炮台": "south",
            "东城炮台": "east",
            "太阳城": "sun"
        }
        target_text = self.city_target.currentText()
        target = target_map.get(target_text, "north")

        queue_mode = "default" if self.city_queue_default.isChecked() else "team12"

        try:
            heal_seconds = int(self.city_heal_seconds.text() or "8")
            wait_seconds = int(self.city_wait_seconds.text() or "0")
        except ValueError:
            self._toast("参数错误：请输入有效数字")
            return

        def runner(should_stop):
            run_sweep_city(
                self.app, self.serial,
                target=target,
                queue_mode=queue_mode,
                heal_seconds=heal_seconds,
                wait_seconds=wait_seconds,
                loop_interval=0,
                toast=self._toast,
                log=lambda m: None,  # 无日志
                should_stop=should_stop,
                threshold=None,
                verbose=False
            )

        self._start_task_with_button("sweep_city", runner, self.outing_btn, "🚀 开始刷王城")

    def _btn_garrison(self):
        """自动驻军"""
        if "garrison" in self._running_tasks:
            self._toast("驻军任务正在运行")
            return

        def runner(should_stop):
            run_auto_garrison(
                self.app, self.serial,
                toast=self._toast,
                log=lambda m: None,
                should_stop=should_stop,
                threshold=None,
                verbose=False
            )

        self._start_task_with_button("garrison", runner, self.garrison_btn, "▶️ 开始驻军")

    def _btn_heal(self):
        """紧急治疗"""
        if "heal" in self._running_tasks:
            self._toast("治疗任务正在运行")
            return

        def runner(should_stop):
            run_emergency_heal(
                self.app, self.serial,
                toast=self._toast,
                log=lambda m: None,
                should_stop=should_stop,
                threshold=None,
                verbose=False
            )

        self._start_task_with_button("heal", runner, self.heal_btn, "🚑 紧急治疗")

    def _btn_init_to_wild(self):
        """初始化到野外"""
        if "init_wild" in self._running_tasks:
            self._toast("初始化任务正在运行")
            return

        def runner(should_stop):
            run_init_to_wild(
                self.app, self.serial,
                toast=self._toast,
                log=lambda m: None,
                threshold=None,
                verbose=False
            )

        self._start_task_with_button("init_wild", runner, self.init_btn, "🌲 初始化到野外")

    def _btn_withdraw(self):
        """一键撤军"""
        if "withdraw" in self._running_tasks:
            self._toast("撤军任务正在运行")
            return

        def runner(should_stop):
            run_withdraw_troops(
                self.app, self.serial,
                toast=self._toast,
                log=lambda m: None,
                should_stop=should_stop,
                threshold=None,
                verbose=False
            )

        self._start_task_with_button("withdraw", runner, self.withdraw_btn, "↩️ 一键撤军")

    def _start_task_with_button(self, task_id: str, runner, button: QPushButton, original_text: str):
        """启动任务并管理按钮状态"""
        if not self.worker:
            self._toast("设备Worker未初始化")
            return

        self._running_tasks.add(task_id)
        button.setText("⏹️ 停止")
        button.setStyleSheet(button.styleSheet().replace("#2196F3", "#F44336").replace("#FF9800", "#F44336").replace("#009688", "#F44336").replace("#9C27B0", "#F44336"))

        def on_click():
            self.worker.stop_task()
            self._sig.reset_button.emit(button, original_text)

        button.clicked.disconnect()
        button.clicked.connect(on_click)

        def task_wrapper():
            try:
                runner(lambda: self.worker.should_stop())
            except Exception as e:
                self._toast(f"任务错误：{e}")
            finally:
                self._running_tasks.discard(task_id)
                self._sig.reset_button.emit(button, original_text)

        self.worker.start_task(task_wrapper)

    def _on_reset_button(self, button: QPushButton, original_text: str):
        """重置按钮状态"""
        button.setText(original_text)
        # 恢复原始颜色
        if "刷全军" in original_text or "刷王城" in original_text:
            color = "#2196F3"
        elif "驻军" in original_text:
            color = "#FF9800"
        elif "治疗" in original_text:
            color = "#F44336"
        elif "初始化" in original_text:
            color = "#009688"
        elif "撤军" in original_text:
            color = "#9C27B0"
        else:
            color = "#4CAF50"

        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }}
            QPushButton:hover {{
                background-color: {self._darken_color(color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(color, 0.3)};
            }}
            QPushButton:disabled {{
                background-color: #CCCCCC;
                color: #666666;
            }}
        """)

        button.clicked.disconnect()
        if "刷全军" in original_text or "刷王城" in original_text:
            button.clicked.connect(self._btn_outing)
        elif "驻军" in original_text:
            button.clicked.connect(self._btn_garrison)
        elif "治疗" in original_text:
            button.clicked.connect(self._btn_heal)
        elif "初始化" in original_text:
            button.clicked.connect(self._btn_init_to_wild)
        elif "撤军" in original_text:
            button.clicked.connect(self._btn_withdraw)

    def _toast(self, msg: str):
        """显示提示"""
        self._sig.toast.emit(msg)

    def _on_toast(self, msg: str):
        """处理提示"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", msg)

    def refresh_status(self):
        """刷新设备状态"""
        ok, _ = self.adb.shell(self.serial, "echo 1")
        status = "在线" if ok else "离线"
        emoji = "✅" if ok else "❌"
        self.title_label.setText(f"{emoji} {self.serial} ({status})")

    def device_log(self, msg: str):
        """设备日志（移动端不显示）"""
        pass


class MobileMainWindow(QWidget):
    """移动端主窗口 - 包含设备标签页"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("📱 MuMu控制器 - 移动端")
        self.resize(480, 800)  # 移动端尺寸

        self._build_ui()

    def _build_ui(self):
        """构建主界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        title_bar = QWidget()
        title_bar.setStyleSheet("background-color: #2196F3; color: white;")
        title_bar.setMinimumHeight(60)
        title_layout = QHBoxLayout(title_bar)

        title_label = QLabel("📱 MuMu控制器")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        layout.addWidget(title_bar)

        # 设备标签页
        self.device_tabs = QTabWidget()
        self.device_tabs.setTabPosition(QTabWidget.North)

        # 设置标签页字体
        tab_font = QFont()
        tab_font.setPointSize(14)
        self.device_tabs.setFont(tab_font)

        # 设置标签页样式
        self.device_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background-color: #E0E0E0;
                color: #333333;
                padding: 12px 20px;
                margin: 2px;
                border-radius: 5px;
            }
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
            }
            QTabBar::tab:hover {
                background-color: #BBDEFB;
            }
        """)

        layout.addWidget(self.device_tabs, 1)

        # 添加设备标签页
        self._add_device_tabs()

    def _get_device_display_name(self, serial: str) -> str:
        """获取设备显示名称（备注或端口）"""
        try:
            # 获取备注
            note = (self.app.cfg.get("notes", {}) or {}).get(serial, "").strip()
            if note:
                return note
            # 没有备注，使用端口号
            return serial.split(":")[-1] if ":" in serial else serial
        except Exception:
            return serial.split(":")[-1] if ":" in serial else serial

    def _add_device_tabs(self):
        """添加设备标签页"""
        # 添加初始页
        from .panels.tools_panel import ToolsPanel
        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(15)

        # 初始页标题
        welcome_label = QLabel("🏠 欢迎使用移动端界面")
        welcome_font = QFont()
        welcome_font.setPointSize(18)
        welcome_font.setBold(True)
        welcome_label.setFont(welcome_font)
        welcome_label.setAlignment(Qt.AlignCenter)
        overview_layout.addWidget(welcome_label)

        # 工具面板（全局操作）
        tools_panel = ToolsPanel(self.app, None)  # None表示全局操作
        overview_layout.addWidget(tools_panel)
        overview_layout.addStretch()

        self.device_tabs.addTab(overview_tab, "🏠 初始页")

        # 获取所有在线设备
        serials = list(self.app.workers.keys())

        if not serials:
            # 没有设备时显示提示
            placeholder = QWidget()
            placeholder_layout = QVBoxLayout(placeholder)
            placeholder_layout.setAlignment(Qt.AlignCenter)

            label = QLabel("📵 暂无设备\n\n请在主界面连接设备")
            label_font = QFont()
            label_font.setPointSize(16)
            label.setFont(label_font)
            label.setAlignment(Qt.AlignCenter)
            placeholder_layout.addWidget(label)

            self.device_tabs.addTab(placeholder, "无设备")
        else:
            # 为每个设备创建标签页
            for serial in serials:
                device_tab = MobileDeviceTab(self.app, serial)
                # 使用备注名称或端口号
                tab_name = self._get_device_display_name(serial)
                self.device_tabs.addTab(device_tab, f"📱 {tab_name}")

    def resizeEvent(self, event):
        """窗口大小改变时的处理"""
        super().resizeEvent(event)
        # 可以在这里根据窗口宽度调整字体大小
        width = self.width()
        if width < 400:
            # 窗口很窄时，缩小字体
            scale_factor = width / 480.0
            # 这里可以动态调整字体大小
