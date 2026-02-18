"""
移动端界面 - 针对小屏幕优化
特点：
1. 大按钮（最小高度70px）
2. 大字体（16-20pt）
3. 自适应换行布局
4. 触摸友好的间距
5. 自动跟随主界面功能更新
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QLineEdit, QComboBox, QGroupBox, QRadioButton,
    QGridLayout, QCheckBox, QScrollArea, QSizePolicy, QFrame, QDialog
)

from ..common.logger import Logger
from ..core.adb import AdbClient
from ..common.worker import DeviceWorker

# 导入主界面的设备标签页，然后通过样式覆盖实现移动端优化
from .device_tab_qt import DeviceTabQt


class MobileMainWindow(QWidget):
    """移动端主窗口 - 包含设备标签页"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        # 代理主应用重要属性，满足 DeviceTabQt 对 app 的依赖
        self.logger = app.logger
        self.adb = app.adb
        self.workers = app.workers
        self.cfg = app.cfg
        # 注意：device_tabs 在主应用中是一个 dict，这里直接复用，避免命名冲突
        self.device_tabs = app.device_tabs
        # 配置管理器（若存在）
        self.config_mgr = getattr(app, 'config_mgr', None)

        self.setWindowTitle("📱 MuMu控制器 - 移动端")
        self.resize(360, 800)  # 移动端尺寸（更窄）
        self.setMinimumWidth(250)  # 最小宽度250px（支持更窄的屏幕）
        self.setMinimumHeight(400)  # 最小高度400px（可调整，支持滚动）

        # 响应式缩放参数
        self.base_width = 360  # 基准宽度
        self.scale_factor = 0.8  # 当前缩放比例（默认缩小20%）

        self._build_ui()

    def _build_ui(self):
        """构建主界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        title_bar = QWidget()
        title_bar.setStyleSheet("background-color: #2196F3; color: white;")
        title_bar.setMinimumHeight(50)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(15, 5, 15, 5)

        title_label = QLabel("📱 MuMu控制器")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        layout.addWidget(title_bar)

        # 选项卡容器（避免与 app.device_tabs 冲突，命名为 tabs）
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)

        # 设置标签页字体
        tab_font = QFont()
        tab_font.setPointSize(13)
        self.tabs.setFont(tab_font)

        # 设置标签页样式
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background-color: #E0E0E0;
                color: #333333;
                padding: 10px 16px;
                margin: 2px;
                border-radius: 5px;
                font-size: 13pt;
            }
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
            }
            QTabBar::tab:hover {
                background-color: #BBDEFB;
            }
        """)

        layout.addWidget(self.tabs, 1)

        # 添加设备标签页
        self._add_device_tabs()
    def append_device_log(self, serial: str, msg: str):
        """
        代理主应用的设备日志接口，满足 DeviceTabQt 对 app.append_device_log 的依赖
        """
        try:
            self.app.append_device_log(serial, msg)
        except Exception:
            pass


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
        # 添加初始页（包滚动容器，避免顶起最小高度）
        overview_tab = self._wrap_in_scroll(self._create_overview_tab())
        self.tabs.addTab(overview_tab, "🏠 初始页")

        # 获取所有在线设备
        serials = list(self.app.workers.keys())

        if not serials:
            # 没有设备时显示提示
            placeholder = QWidget()
            placeholder_layout = QVBoxLayout(placeholder)
            placeholder_layout.setAlignment(Qt.AlignCenter)

            label = QLabel("📵 暂无设备\n\n请在主界面连接设备")
            label_font = QFont()
            label_font.setPointSize(15)
            label.setFont(label_font)
            label.setAlignment(Qt.AlignCenter)
            placeholder_layout.addWidget(label)

            self.tabs.addTab(placeholder, "无设备")
        else:
            # 为每个设备创建标签页（使用主界面DeviceTabQt + 移动端样式）
            for serial in serials:
                # 传入当前窗口作为 app（父级是 QWidget），以满足 DeviceTabQt 的父级要求
                device_tab = DeviceTabQt(self, serial)
                # 应用移动端样式
                self._apply_mobile_styles(device_tab)
                # 建立 app 级映射，供全局模式等功能使用
                self.device_tabs[serial] = device_tab
                # 使用备注名称或端口号
                tab_name = self._get_device_display_name(serial)
                # 包装为可滚动页面，避免最小高度异常
                self.tabs.addTab(self._wrap_in_scroll(device_tab), f"📱 {tab_name}")

    def _create_overview_tab(self) -> QWidget:
        """创建初始页 - 包含全局功能按钮"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)  # 减少边距
        layout.setSpacing(10)  # 减少间距

        # 欢迎标题
        welcome_label = QLabel("🏠 移动端控制中心")
        welcome_font = QFont()
        welcome_font.setPointSize(14)  # 减小字体
        welcome_font.setBold(True)
        welcome_label.setFont(welcome_font)
        welcome_label.setAlignment(Qt.AlignCenter)
        welcome_label.setMaximumHeight(30)  # 限制高度
        layout.addWidget(welcome_label)

        # 说明文字
        info_label = QLabel(
            "移动端界面提供与主界面完全一致的功能\n"
            "所有参数和设置都已同步\n\n"
            "请选择设备标签页开始使用"
        )
        info_font = QFont()
        info_font.setPointSize(10)  # 减小字体
        info_label.setFont(info_font)
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setWordWrap(True)
        info_label.setMaximumHeight(80)  # 限制高度
        layout.addWidget(info_label)

        # 全局功能按钮组
        global_box = QGroupBox("🌐 全局功能")
        global_box_font = QFont()
        global_box_font.setPointSize(12)  # 减小字体
        global_box_font.setBold(True)
        global_box.setFont(global_box_font)
        global_layout = QVBoxLayout(global_box)
        global_layout.setSpacing(8)  # 减少间距

        # 自动连接MuMu按钮（低饱和度蓝色）
        self.btn_auto_connect = self._create_mobile_button("🔌 自动连接MuMu", "#5A7A8C")
        self.btn_auto_connect.clicked.connect(self._on_auto_connect_mumu)
        global_layout.addWidget(self.btn_auto_connect)

        # 置顶按钮（低饱和度橙色）
        self.btn_toggle_topmost = self._create_mobile_button("📌 窗口置顶", "#8C7A5A")
        self.btn_toggle_topmost.clicked.connect(self._on_toggle_topmost)
        global_layout.addWidget(self.btn_toggle_topmost)

        # 全局操作模式按钮（低饱和度绿色/紫色）
        global_mode_enabled = self.app.cfg.get("global_mode", False)
        if global_mode_enabled:
            self.btn_global_mode = self._create_mobile_button("⚙️ 全局模式：开启", "#6A8C5A")
        else:
            self.btn_global_mode = self._create_mobile_button("⚙️ 全局模式：关闭", "#7A5A8C")
        self.btn_global_mode.clicked.connect(self._on_global_mode)
        global_layout.addWidget(self.btn_global_mode)

        # 停止所有按钮（低饱和度红色）
        self.btn_stop_all = self._create_mobile_button("⏹️ 停止所有任务", "#8C5A5A")
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        global_layout.addWidget(self.btn_stop_all)

        # 掉线监控（移动端）：若主应用方法可用则复用，否则提示仅桌面可用
        self.btn_offline_watch = QPushButton("📡 掉线监控")
        self.btn_offline_watch.setCheckable(True)
        self.btn_offline_watch.setMinimumHeight(35)
        self.btn_offline_watch.setMaximumHeight(35)
        if hasattr(self.app, "toggle_offline_watch"):
            self.btn_offline_watch.toggled.connect(self._on_toggle_offline_watch)
        else:
            self.btn_offline_watch.toggled.connect(self._on_mobile_offline_watch_fallback)
        global_layout.addWidget(self.btn_offline_watch)
        layout.addWidget(global_box)
        return tab


    def _on_mobile_offline_watch_fallback(self, checked: bool):
        try:
            # 移动端独立运行暂不提供完整版配置对话框，给出提示并复位按钮状态
            if checked:
                self._toast("当前为移动端独立运行，完整版掉线监控仅在桌面主界面可用")
            self.btn_offline_watch.setChecked(False)
        except Exception:
            pass

    def _on_toggle_offline_watch(self, checked: bool):
        """通过 UI 线程调度调用主应用的掉线监控，避免跨线程父子关系/QTimer 错误"""
        try:
            QTimer.singleShot(0, lambda: self.app.toggle_offline_watch(checked))
        except Exception:
            # 失败则复位按钮
            try:
                self.btn_offline_watch.setChecked(False)
            except Exception:
                pass

    def _toast(self, text: str):
        """简易非阻塞提示（3秒自动关闭）"""
        try:
            dlg = QDialog(self)
            dlg.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            dlg.setAttribute(Qt.WA_TranslucentBackground, True)
            lay = QVBoxLayout(dlg)
            lab = QLabel(text)
            lab.setStyleSheet("QLabel { background: rgba(30,30,30,200); color:#eee; border-radius:6px; padding:10px 14px; }")
            lay.addWidget(lab)
            dlg.adjustSize()
            g = self.geometry()
            pos = self.mapToGlobal(g.bottomRight())
            dlg.move(pos.x() - dlg.width() - 20, pos.y() - dlg.height() - 20)
            dlg.show()
            QTimer.singleShot(3000, dlg.close)
        except Exception:
            pass



    def _create_mobile_button(self, text: str, color: str) -> QPushButton:
        """创建移动端按钮（高度减半）"""
        btn = QPushButton(text)
        btn.setMinimumHeight(35)  # 70 / 2 = 35
        btn.setMaximumHeight(35)  # 固定高度，防止拉伸
        font = QFont()
        font.setPointSize(11)  # 18 / 2 ≈ 11
        font.setBold(True)
        btn.setFont(font)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px;
            }}
            QPushButton:hover {{
                background-color: {self._darken_color(color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(color, 0.3)};
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

    def _on_auto_connect_mumu(self):
        """自动连接MuMu"""
        try:
            self.app.auto_connect_mumu()
        except Exception as e:
            print(f"自动连接失败: {e}")

    def _on_toggle_topmost(self):
        """切换窗口置顶"""
        try:
            # 保存当前位置和大小
            geometry = self.geometry()

            if self.windowFlags() & Qt.WindowStaysOnTopHint:
                # 取消置顶
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
                self.btn_toggle_topmost.setText("📌 窗口置顶")
            else:
                # 设置置顶
                self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
                self.btn_toggle_topmost.setText("📌 取消置顶")

            # 恢复位置和大小
            self.setGeometry(geometry)
            # 重新显示窗口
            self.show()
            # 激活窗口
            self.activateWindow()
        except Exception as e:
            print(f"切换置顶失败: {e}")

    def _on_global_mode(self):
        """切换全局操作模式"""
        try:
            # 获取当前状态
            current = self.app.cfg.get("global_mode", False)
            # 切换状态
            new_state = not current
            self.app.cfg["global_mode"] = new_state
            self.app.config_mgr.save(self.app.cfg)
            # 更新按钮文字
            if new_state:
                self.btn_global_mode.setText("⚙️ 全局模式：开启")
                self.btn_global_mode.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        color: white;
                        border: none;
                        border-radius: 10px;
                        padding: 15px;
                    }
                """)
            else:
                self.btn_global_mode.setText("⚙️ 全局模式：关闭")
                self.btn_global_mode.setStyleSheet("""
                    QPushButton {
                        background-color: #9C27B0;
                        color: white;
                        border: none;
                        border-radius: 10px;
                        padding: 15px;
                    }
                """)
            # 同步主界面的复选框
            if hasattr(self.app, 'chk_global_mode'):
                self.app.chk_global_mode.setChecked(new_state)
        except Exception as e:
            print(f"切换全局操作模式失败: {e}")

    def _on_stop_all(self):
        """停止所有任务"""
        try:
            self.app.stop_all_now()
        except Exception as e:
            print(f"停止所有任务失败: {e}")

    def _get_device_display_name(self, serial: str) -> str:
        """获取设备显示名称（备注或端口）"""
        try:
            note = (self.app.cfg.get("notes", {}) or {}).get(serial, "").strip()
            if note:
                return note
            return serial.split(":")[-1] if ":" in serial else serial
        except Exception:
            return serial.split(":")[-1] if ":" in serial else serial

    def _wrap_in_scroll(self, content: QWidget) -> QScrollArea:
        """将内容包装在滚动区域中，统一控制布局与最小高度问题"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 内容不强制扩展高度，避免顶起窗口最小高度
        content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        scroll.setWidget(content)
        return scroll

    def _normalize_layouts(self, widget: QWidget):
        """递归统一所有布局的间距与边距，避免空隙过大/不一致"""
        layout = widget.layout()
        if layout is not None:
            try:
                layout.setSpacing(6)
                layout.setContentsMargins(6, 6, 6, 6)
            except Exception:
                pass
        # 递归子控件
        for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            if child.parent() == widget:
                self._normalize_layouts(child)

    def _apply_mobile_styles(self, widget: QWidget):
        """
        递归应用移动端样式到DeviceTabQt及其所有子控件
        - 大按钮（70px高）
        - 大字体（16-20pt）
        - 触摸友好间距
        - 单列布局优化
        """
        # 全局样式表（按钮高度减半，减少间隙，增加边框）
        mobile_stylesheet = """
            /* 按钮样式 - 高度减半（28px） */
            QPushButton {
                min-height: 28px;
                font-size: 11pt;
                font-weight: bold;
                padding: 4px 8px;
                border-radius: 4px;
                border: 2px solid #555555;
                background-color: #3a3a3a;
            }

            QPushButton:hover {
                background-color: #4a4a4a;
                border: 2px solid #666666;
            }

            QPushButton:pressed {
                background-color: #2a2a2a;
            }

            /* 输入框样式 - 高度减半（20px） */
            QLineEdit {
                min-height: 20px;
                min-width: 60px;
                font-size: 10pt;
                padding: 3px;
                border-radius: 3px;
                border: 2px solid #555555;
                background-color: #2a2a2a;
            }

            /* 下拉框样式 - 高度减半（20px） */
            QComboBox {
                min-height: 20px;
                font-size: 10pt;
                padding: 3px;
                border-radius: 3px;
                border: 2px solid #555555;
                background-color: #2a2a2a;
            }

            /* 标签样式 - 字体减小 */
            QLabel {
                font-size: 10pt;
            }

            /* 分组框标题样式 - 减少边距 */
            QGroupBox {
                font-size: 11pt;
                font-weight: bold;
                padding-top: 8px;
                margin-top: 4px;
            }

            /* 单选按钮样式 - 减少间距 */
            QRadioButton {
                font-size: 10pt;
                spacing: 4px;
            }

            /* 复选框样式 - 减少间距 */
            QCheckBox {
                font-size: 10pt;
                spacing: 4px;
            }

            /* 标签页样式 */
            QTabWidget::pane {
                border: 1px solid #cccccc;
            }

            QTabBar::tab {
                min-height: 24px;
                min-width: 48px;
                font-size: 10pt;
                padding: 4px;
            }
        """

        # 应用样式表到整个widget
        widget.setStyleSheet(mobile_stylesheet)

        # 递归调整所有子控件
        self._adjust_widget_recursive(widget)

        # 统一所有布局的间距/边距，避免大空隙
        self._normalize_layouts(widget)

        # 调整布局为单列模式
        self._convert_to_single_column(widget)

    def _adjust_widget_recursive(self, widget: QWidget):
        """递归调整所有子控件的字体和尺寸（高度减半）"""
        # 调整当前控件
        if isinstance(widget, QPushButton):
            widget.setMinimumHeight(28)  # 56 / 2 = 28
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            font = widget.font()
            font.setPointSize(11)  # 减小字体
            font.setBold(True)
            widget.setFont(font)

        elif isinstance(widget, QLineEdit):
            widget.setMinimumHeight(20)  # 40 / 2 = 20
            widget.setMinimumWidth(60)  # 减小宽度
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            font = widget.font()
            font.setPointSize(10)  # 减小字体
            widget.setFont(font)

        elif isinstance(widget, QComboBox):
            widget.setMinimumHeight(20)  # 40 / 2 = 20
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            font = widget.font()
            font.setPointSize(10)  # 减小字体
            widget.setFont(font)

        elif isinstance(widget, QLabel):
            font = widget.font()
            # 标题标签更大
            if "设备：" in widget.text() or "📱" in widget.text():
                font.setPointSize(12)  # 标题字体
                font.setBold(True)
            else:
                font.setPointSize(10)  # 普通字体
            widget.setFont(font)
            widget.setWordWrap(True)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        elif isinstance(widget, QGroupBox):
            font = widget.font()
            font.setPointSize(11)  # 分组框字体
            font.setBold(True)
            widget.setFont(font)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        elif isinstance(widget, QRadioButton):
            font = widget.font()
            font.setPointSize(10)  # 单选按钮字体
            widget.setFont(font)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        elif isinstance(widget, QCheckBox):
            # 复选框字体
            font = widget.font()
            font.setPointSize(10)  # 复选框字体
            widget.setFont(font)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # 递归处理所有子控件
        for child in widget.findChildren(QWidget):
            # 只处理直接子控件，避免重复处理
            if child.parent() == widget:
                self._adjust_widget_recursive(child)

    def _convert_to_single_column(self, widget: QWidget):
        """
        将主界面的多列布局转换为移动端的单列布局
        主界面：按钮1 按钮2 按钮3（横向排列）
        移动端：按钮1
               按钮2
               按钮3（纵向排列）
        """
        # 递归处理所有子控件
        self._convert_layout_recursive(widget)

    def _convert_layout_recursive(self, widget: QWidget):
        """递归转换所有布局为单列"""
        # 处理当前控件的布局
        layout = widget.layout()

        if layout is not None:
            # 转换HBoxLayout为VBoxLayout
            if layout.__class__.__name__ == 'QHBoxLayout':
                self._convert_hbox_to_vbox(widget, layout)

            # 转换GridLayout为单列
            elif isinstance(layout, QGridLayout):
                self._convert_grid_to_single_column(widget, layout)

        # 递归处理所有子控件
        for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            if child.parent() == widget:
                self._convert_layout_recursive(child)

    def _convert_hbox_to_vbox(self, widget: QWidget, hbox_layout):
        """将HBoxLayout转换为VBoxLayout"""
        from PySide6.QtWidgets import QVBoxLayout, QSpacerItem, QSizePolicy

        # 收集所有子控件和spacer
        items = []
        for i in range(hbox_layout.count()):
            item = hbox_layout.itemAt(i)
            if item:
                if item.widget():
                    items.append(('widget', item.widget()))
                elif item.spacerItem():
                    items.append(('spacer', item.spacerItem()))

        # 如果子控件数量较多（>2个按钮），转换为垂直布局
        widget_count = sum(1 for t, _ in items if t == 'widget')
        if widget_count > 2:
            # 移除所有项目
            while hbox_layout.count():
                item = hbox_layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)

            # 创建新的垂直布局
            vbox_layout = QVBoxLayout()
            vbox_layout.setSpacing(8)  # 减少间距（从15到8）
            vbox_layout.setContentsMargins(0, 0, 0, 0)

            # 添加所有控件到垂直布局
            for item_type, item_obj in items:
                if item_type == 'widget':
                    vbox_layout.addWidget(item_obj)

            # 替换布局
            QWidget().setLayout(widget.layout())  # 删除旧布局
            widget.setLayout(vbox_layout)

    def _convert_grid_to_single_column(self, widget: QWidget, grid_layout: QGridLayout):
        """将GridLayout转换为单列布局"""
        from PySide6.QtWidgets import QVBoxLayout

        # 获取网格的行数和列数
        row_count = grid_layout.rowCount()
        col_count = grid_layout.columnCount()

        # 如果只有1列或2列，保持原样
        if col_count <= 2:
            # 只调整间距
            grid_layout.setHorizontalSpacing(6)  # 减少水平间距
            grid_layout.setVerticalSpacing(8)    # 减少垂直间距
            return

        # 如果有多列（>2），转换为单列
        # 收集所有控件（按行优先顺序）
        items = []
        for row in range(row_count):
            for col in range(col_count):
                item = grid_layout.itemAtPosition(row, col)
                if item and item.widget():
                    items.append(item.widget())

        # 如果没有控件，直接返回
        if not items:
            return

        # 移除所有项目
        while grid_layout.count():
            item = grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # 创建新的垂直布局
        vbox_layout = QVBoxLayout()
        vbox_layout.setSpacing(8)  # 减少间距
        vbox_layout.setContentsMargins(0, 0, 0, 0)

        # 添加所有控件到垂直布局
        for item_widget in items:
            vbox_layout.addWidget(item_widget)

        # 替换布局
        QWidget().setLayout(widget.layout())  # 删除旧布局
        widget.setLayout(vbox_layout)

    def resizeEvent(self, event):
        """窗口大小改变时，动态调整界面元素大小"""
        super().resizeEvent(event)

        # 获取当前宽度
        current_width = self.width()

        # 计算缩放比例
        # 基准宽度360px，缩放比例1.0
        # 宽度300px时，缩放比例0.85
        # 宽度250px时，缩放比例0.7
        if current_width >= self.base_width:
            new_scale = 1.0
        elif current_width >= 300:
            # 360-300之间，线性缩放1.0-0.85
            new_scale = 0.85 + (current_width - 300) / (self.base_width - 300) * 0.15
        else:
            # 300-250之间，线性缩放0.85-0.7
            new_scale = 0.7 + (current_width - 250) / (300 - 250) * 0.15

        # 如果缩放比例变化超过5%，才重新应用样式
        if abs(new_scale - self.scale_factor) > 0.05:
            self.scale_factor = new_scale
            self._apply_responsive_scale()

    def _apply_responsive_scale(self):
        """应用响应式缩放（基于减半后的尺寸）"""
        # 计算缩放后的尺寸（基准已经是减半）
        button_height = int(28 * self.scale_factor)  # 基准28px（56/2）
        input_height = int(20 * self.scale_factor)   # 基准20px（40/2）
        button_font_size = int(11 * self.scale_factor)  # 基准11pt
        input_font_size = int(10 * self.scale_factor)   # 基准10pt
        label_font_size = int(10 * self.scale_factor)   # 基准10pt

        # 更新全局样式表
        scaled_stylesheet = f"""
            QPushButton {{
                min-height: {button_height}px;
                font-size: {button_font_size}pt;
                font-weight: bold;
                padding: {int(4 * self.scale_factor)}px {int(8 * self.scale_factor)}px;
                border-radius: {int(4 * self.scale_factor)}px;
                border: 2px solid #555555;
                background-color: #3a3a3a;
            }}

            QPushButton:hover {{
                background-color: #4a4a4a;
                border: 2px solid #666666;
            }}

            QPushButton:pressed {{
                background-color: #2a2a2a;
            }}

            QLineEdit {{
                min-height: {input_height}px;
                min-width: {int(60 * self.scale_factor)}px;
                font-size: {input_font_size}pt;
                padding: {int(3 * self.scale_factor)}px;
                border-radius: {int(3 * self.scale_factor)}px;
                border: 2px solid #555555;
                background-color: #2a2a2a;
            }}

            QComboBox {{
                min-height: {input_height}px;
                font-size: {input_font_size}pt;
                padding: {int(3 * self.scale_factor)}px;
                border-radius: {int(3 * self.scale_factor)}px;
                border: 2px solid #555555;
                background-color: #2a2a2a;
            }}

            QLabel {{
                font-size: {label_font_size}pt;
            }}

            QGroupBox {{
                font-size: {int(11 * self.scale_factor)}pt;
                font-weight: bold;
                padding-top: {int(8 * self.scale_factor)}px;
                margin-top: {int(4 * self.scale_factor)}px;
            }}

            QRadioButton {{
                font-size: {label_font_size}pt;
                spacing: {int(4 * self.scale_factor)}px;
            }}

            QCheckBox {{
                font-size: {label_font_size}pt;
                spacing: {int(4 * self.scale_factor)}px;
            }}

            QTabBar::tab {{
                min-height: {int(24 * self.scale_factor)}px;
                min-width: {int(48 * self.scale_factor)}px;
                font-size: {label_font_size}pt;
                padding: {int(4 * self.scale_factor)}px;
            }}
        """

        # 应用到所有设备标签页
        if hasattr(self, 'tabs'):
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if tab:
                    tab.setStyleSheet(scaled_stylesheet)

