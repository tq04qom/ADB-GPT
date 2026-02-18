from __future__ import annotations

from typing import Dict, Optional, Callable

from PySide6.QtCore import Qt, QSize, QRectF, QTimer
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QMainWindow, QToolBar, QLabel,
    QPushButton, QComboBox, QFrame, QGraphicsView, QGraphicsScene,
    QGraphicsProxyWidget, QSizePolicy, QLineEdit, QRadioButton, QTabWidget,
    QScrollArea
)


# ---------------- Zoomable GraphicsView ----------------
class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: Optional[QWidget] = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._scale = 1.0
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    # Ctrl + Wheel to zoom, plain wheel scrolls
    def wheelEvent(self, e):  # type: ignore
        if e.modifiers() & Qt.ControlModifier:
            delta = e.angleDelta().y()
            factor = 1.0015 ** delta
            self._apply_zoom(self._scale * factor)
            e.accept()
            return
        super().wheelEvent(e)

    def _apply_zoom(self, target: float) -> None:
        target = max(0.3, min(3.0, target))
        f = target / self._scale
        self._scale = target
        self.scale(f, f)

    def zoom_in(self):
        self._apply_zoom(self._scale * 1.2)

    def zoom_out(self):
        self._apply_zoom(self._scale / 1.2)

    def zoom_reset(self):
        self.resetTransform()
        self._scale = 1.0


# ---------------- Content building helpers ----------------
class MobileSeparator(QWidget):
    def __init__(self, title: str = "") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 18, 0, 6)
        lay.setSpacing(8)
        line1 = QFrame(); line1.setFrameShape(QFrame.HLine); line1.setFrameShadow(QFrame.Sunken)
        line2 = QFrame(); line2.setFrameShape(QFrame.HLine); line2.setFrameShadow(QFrame.Sunken)
        if title:
            lab = QLabel(title)
            lab.setStyleSheet("color:#666;font-weight:bold;")
            lay.addWidget(line1, 1)
            lay.addWidget(lab)
            lay.addWidget(line2, 1)
        else:
            lay.addWidget(line1)


class MobileRow(QWidget):
    def __init__(self, widget: QWidget) -> None:
        super().__init__()
        self.setFixedHeight(40)  # 20行可见（800/40 = 20）
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.addWidget(widget)


class MobileContentWidget(QWidget):
    """Fixed-width content container which grows vertically.
    Base width is 400 and height auto-expands per added rows.
    """

    def __init__(self, app) -> None:  # app = AppQt
        super().__init__()
        self.app = app
        self.setObjectName("MobileContent")
        self._base_width = 400  # 修改为400（无滚动条）

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 固定顶部区域（不受滚动影响）===
        fixed_top = QWidget()
        fixed_top.setObjectName("FixedTop")
        fixed_top_layout = QVBoxLayout(fixed_top)
        fixed_top_layout.setContentsMargins(8, 8, 8, 4)
        fixed_top_layout.setSpacing(4)

        # 全局功能栏（始终显示在顶部，占1行）
        global_bar = QWidget()
        global_h = QHBoxLayout(global_bar)
        global_h.setContentsMargins(0, 0, 0, 0)
        global_h.setSpacing(4)

        # 紧凑的全局按钮
        btn_connect = QPushButton("🔌")
        btn_connect.setToolTip("自动连接MuMu")
        btn_connect.setFixedSize(35, 35)
        btn_connect.clicked.connect(self._act_auto_connect_mumu)
        global_h.addWidget(btn_connect)

        self.btn_topmost = QPushButton("📌")
        self.btn_topmost.setToolTip("窗口置顶")
        self.btn_topmost.setFixedSize(35, 35)
        self.btn_topmost.clicked.connect(self._act_toggle_topmost)
        global_h.addWidget(self.btn_topmost)

        self.btn_global = QPushButton("⚙️")
        self.btn_global.setToolTip("全局模式: 关闭")
        self.btn_global.setFixedSize(35, 35)
        self.btn_global.clicked.connect(self._act_toggle_global_mode)
        global_h.addWidget(self.btn_global)

        btn_stop = QPushButton("⏹️")
        btn_stop.setToolTip("停止所有")
        btn_stop.setFixedSize(35, 35)
        btn_stop.clicked.connect(self._act_stop_all)
        global_h.addWidget(btn_stop)

        global_h.addWidget(QLabel("速度:"))
        self.speed_input = QLineEdit("1.0")
        self.speed_input.setFixedWidth(50)
        self.speed_input.textChanged.connect(self._on_speed_changed)
        global_h.addWidget(self.speed_input)

        global_h.addStretch()
        fixed_top_layout.addWidget(global_bar)

        # 初始化全局模式按钮状态
        self._update_global_mode_button()

        # 设备标签页（占第二行）
        self.device_tabs = QTabWidget()
        self.device_tabs.setTabPosition(QTabWidget.North)
        self.device_tabs.setMaximumHeight(35)  # 限制标签页高度
        # 允许标签重排，并支持双击分离
        try:
            self.device_tabs.setMovable(True)
            if hasattr(self.device_tabs, "tabBarDoubleClicked"):
                self.device_tabs.tabBarDoubleClicked.connect(self._on_tab_bar_double_clicked)
        except Exception:
            pass

        # 为每个设备创建一个标签页，内容为空（只用标签）
        self._detached_windows: Dict[str, QMainWindow] = {}
        self.device_tab_widgets: Dict[str, QWidget] = {}
        self._widget_serial: Dict[QWidget, str] = {}
        for serial in list(getattr(self.app, "device_tabs", {}).keys()):
            tab_widget = QWidget()
            self.device_tab_widgets[serial] = tab_widget
            self._widget_serial[tab_widget] = serial
            # 只显示别名部分
            display_name = self._display_name(serial)
            if "(" in display_name:
                tab_name = display_name.split("(")[0].strip()
            else:
                tab_name = serial[:8] + "..." if len(serial) > 8 else serial
            self.device_tabs.addTab(tab_widget, tab_name)

        fixed_top_layout.addWidget(self.device_tabs)
        main_layout.addWidget(fixed_top)

        # === 可滚动内容区域 ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 隐藏横向滚动条
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 隐藏纵向滚动条
        scroll_area.setFrameShape(QFrame.NoFrame)

        # 滚动内容容器
        scroll_content = QWidget()
        self.v = QVBoxLayout(scroll_content)
        self.v.setContentsMargins(8, 4, 8, 8)
        self.v.setSpacing(4)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, 1)

        # 出征功能
        self.v.addWidget(MobileSeparator("出征+治疗"))

        # 任务类型选择
        task_row = QWidget()
        task_h = QHBoxLayout(task_row)
        task_h.setContentsMargins(0, 0, 0, 0)
        task_h.setSpacing(8)
        lbl_task = QLabel("任务:")
        lbl_task.setStyleSheet("font-size: 14pt;")
        task_h.addWidget(lbl_task)
        self.mode_army = QRadioButton("刷全军")
        self.mode_city = QRadioButton("刷王城")
        # 设置单选按钮字体大小
        self.mode_army.setStyleSheet("font-size: 14pt;")
        self.mode_city.setStyleSheet("font-size: 14pt;")
        self.mode_army.setChecked(True)
        task_h.addWidget(self.mode_army)
        task_h.addWidget(self.mode_city)
        task_h.addStretch()
        self.v.addWidget(MobileRow(task_row))

        # 刷全军参数（第一行）
        army_row1 = QWidget()
        army_h1 = QHBoxLayout(army_row1)
        army_h1.setContentsMargins(0, 0, 0, 0)
        army_h1.setSpacing(8)
        lbl_sec = QLabel("持续秒数:")
        lbl_sec.setStyleSheet("font-size: 14pt;")
        army_h1.addWidget(lbl_sec)
        self.sweep_seconds = QLineEdit("8")
        self.sweep_seconds.setFixedWidth(60)
        self.sweep_seconds.setStyleSheet("font-size: 14pt;")
        army_h1.addWidget(self.sweep_seconds)
        lbl_loop = QLabel("循环:")
        lbl_loop.setStyleSheet("font-size: 14pt;")
        army_h1.addWidget(lbl_loop)
        self.sweep_loops = QLineEdit("1")
        self.sweep_loops.setFixedWidth(50)
        self.sweep_loops.setStyleSheet("font-size: 14pt;")
        army_h1.addWidget(self.sweep_loops)
        self.v.addWidget(MobileRow(army_row1))

        # 刷王城参数（第一行）
        city_row1 = QWidget()
        city_h1 = QHBoxLayout(city_row1)
        city_h1.setContentsMargins(0, 0, 0, 0)
        city_h1.setSpacing(8)
        lbl_target = QLabel("目标:")
        lbl_target.setStyleSheet("font-size: 14pt;")
        city_h1.addWidget(lbl_target)
        self.city_target = QComboBox()
        self.city_target.addItems(["北地炮台", "西城炮台", "南翼炮台", "东城炮台", "太阳城"])
        self.city_target.setStyleSheet("font-size: 14pt;")
        city_h1.addWidget(self.city_target, 1)
        self.v.addWidget(MobileRow(city_row1))

        # 刷王城参数（第二行）
        city_row2 = QWidget()
        city_h2 = QHBoxLayout(city_row2)
        city_h2.setContentsMargins(0, 0, 0, 0)
        city_h2.setSpacing(8)
        lbl_heal = QLabel("治疗:")
        lbl_heal.setStyleSheet("font-size: 14pt;")
        city_h2.addWidget(lbl_heal)
        self.city_heal_seconds = QLineEdit("8")
        self.city_heal_seconds.setFixedWidth(50)
        self.city_heal_seconds.setStyleSheet("font-size: 14pt;")
        city_h2.addWidget(self.city_heal_seconds)
        lbl_wait = QLabel("等待:")
        lbl_wait.setStyleSheet("font-size: 14pt;")
        city_h2.addWidget(lbl_wait)
        self.city_wait_seconds = QLineEdit("0")
        self.city_wait_seconds.setFixedWidth(50)
        self.city_wait_seconds.setStyleSheet("font-size: 14pt;")
        city_h2.addWidget(self.city_wait_seconds)
        city_h2.addStretch()
        self.v.addWidget(MobileRow(city_row2))

        # 开始按钮
        self._add_action_button("▶️ 开始出征", self._act_start_outing)

        # 驻军功能
        self.v.addWidget(MobileSeparator("驻军"))

        garrison_row = QWidget()
        garrison_h = QHBoxLayout(garrison_row)
        garrison_h.setContentsMargins(0, 0, 0, 0)
        garrison_h.setSpacing(8)
        garrison_h.addWidget(QLabel("模式:"))
        self.garrison_mode = QComboBox()
        self.garrison_mode.addItems(["乔伊", "收菜"])
        garrison_h.addWidget(self.garrison_mode)
        btn_garrison = self._create_button("开始驻军", self._act_garrison)
        btn_heal = self._create_button("紧急治疗", self._act_emergency_heal)
        garrison_h.addWidget(btn_garrison)
        garrison_h.addWidget(btn_heal)
        self.v.addWidget(MobileRow(garrison_row))

        # 燃霜模式（在驻军下一行）
        ranshuang_row = QWidget()
        ranshuang_h = QHBoxLayout(ranshuang_row)
        ranshuang_h.setContentsMargins(0, 0, 0, 0)
        ranshuang_h.setSpacing(8)
        btn_ranshuang = self._create_button("开始燃霜模式", self._act_ranshuang)
        ranshuang_h.addWidget(btn_ranshuang)
        ranshuang_h.addStretch()
        self.v.addWidget(MobileRow(ranshuang_row))

        # 小工具
        self.v.addWidget(MobileSeparator("小工具"))

        tools_row = QWidget()
        tools_h = QHBoxLayout(tools_row)
        tools_h.setContentsMargins(0, 0, 0, 0)
        tools_h.setSpacing(8)
        btn_shot = self._create_button("📸 截图", self._act_screenshot)
        btn_init = self._create_button("🌲 野外", self._act_init_wild)
        btn_withdraw = self._create_button("🔙 撤军", self._act_withdraw)
        tools_h.addWidget(btn_shot)
        tools_h.addWidget(btn_init)
        tools_h.addWidget(btn_withdraw)
        self.v.addWidget(MobileRow(tools_row))

        # 资源功能
        self.v.addWidget(MobileSeparator("资源"))

        resource_row = QWidget()
        resource_h = QHBoxLayout(resource_row)
        resource_h.setContentsMargins(0, 0, 0, 0)
        resource_h.setSpacing(8)
        btn_edit_coords = self._create_button("编辑坐标", self._act_edit_coords)
        btn_attack = self._create_button("打资源", self._act_attack_resources)
        resource_h.addWidget(btn_edit_coords)
        resource_h.addWidget(btn_attack)
        self.v.addWidget(MobileRow(resource_row))

        # 打熊功能
        self.v.addWidget(MobileSeparator("打熊"))

        # 第一行：打熊时间 + 执行日
        bear_row1 = QWidget()
        bear_h1 = QHBoxLayout(bear_row1)
        bear_h1.setContentsMargins(0, 0, 0, 0)
        bear_h1.setSpacing(8)
        bear_h1.addWidget(QLabel("时间:"))
        self.bear_time = QLineEdit("203000")
        self.bear_time.setFixedWidth(80)
        self.bear_time.setStyleSheet("font-size: 14pt;")
        bear_h1.addWidget(self.bear_time)
        bear_h1.addWidget(QLabel("执行日:"))
        self.bear_day = QComboBox()
        self.bear_day.addItems(["单双日皆打", "仅单日", "仅双日"])
        self.bear_day.setStyleSheet("font-size: 14pt;")
        bear_h1.addWidget(self.bear_day, 1)
        self.v.addWidget(MobileRow(bear_row1))

        # 第二行：车头模式 + 发车间隔
        bear_row2 = QWidget()
        bear_h2 = QHBoxLayout(bear_row2)
        bear_h2.setContentsMargins(0, 0, 0, 0)
        bear_h2.setSpacing(8)
        bear_h2.addWidget(QLabel("车头:"))
        self.bear_head = QComboBox()
        self.bear_head.addItems(["固定车头", "随机上车"])
        self.bear_head.setStyleSheet("font-size: 14pt;")
        bear_h2.addWidget(self.bear_head, 1)
        bear_h2.addWidget(QLabel("间隔:"))
        self.bear_interval = QLineEdit("300")
        self.bear_interval.setFixedWidth(60)
        self.bear_interval.setStyleSheet("font-size: 14pt;")
        bear_h2.addWidget(self.bear_interval)
        self.v.addWidget(MobileRow(bear_row2))

        # 第三行：启动按钮
        bear_row3 = QWidget()
        bear_h3 = QHBoxLayout(bear_row3)
        bear_h3.setContentsMargins(0, 0, 0, 0)
        bear_h3.setSpacing(8)
        self.btn_bear = self._create_button("启动打熊", self._act_bear_mode)
        bear_h3.addWidget(self.btn_bear, 1)
        self.v.addWidget(MobileRow(bear_row3))

        # 联盟功能
        self.v.addWidget(MobileSeparator("联盟"))

        # 第一行：关闭上车 + 打开上车
        alliance_row1 = QWidget()
        alliance_h1 = QHBoxLayout(alliance_row1)
        alliance_h1.setContentsMargins(0, 0, 0, 0)
        alliance_h1.setSpacing(8)
        btn_close_help = self._create_button("关闭上车", self._act_close_help)
        btn_open_help = self._create_button("打开上车", self._act_open_help)
        alliance_h1.addWidget(btn_close_help)
        alliance_h1.addWidget(btn_open_help)
        self.v.addWidget(MobileRow(alliance_row1))

        # 第二行：自动点赞 + 秒进集结 + 一键四阶（合并为两排）
        alliance_row2 = QWidget()
        alliance_h2 = QHBoxLayout(alliance_row2)
        alliance_h2.setContentsMargins(0, 0, 0, 0)
        alliance_h2.setSpacing(8)
        btn_like = self._create_button("自动点赞", self._act_auto_like)
        btn_fast_join = self._create_button("秒进集结", self._act_fast_join)
        btn_rank4 = self._create_button("一键四阶", self._act_rank4)
        alliance_h2.addWidget(btn_like)
        alliance_h2.addWidget(btn_fast_join)
        alliance_h2.addWidget(btn_rank4)
        self.v.addWidget(MobileRow(alliance_row2))

        self.v.addStretch(1)  # allow infinite growth downward
        self.setStyleSheet(
            """
            QPushButton { height: 60px; font-size: 16px; }
            QComboBox, QLabel { font-size: 15px; }
            """
        )

        # 按钮状态同步定时器
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._sync_button_states)
        self._sync_timer.start(500)  # 每500ms同步一次

    def sizeHint(self):  # type: ignore
        # width fixed, height from layout
        sh = super().sizeHint()
        return QSize(self._base_width, max(sh.height(), 1280))

    def minimumSizeHint(self):  # type: ignore
        return QSize(self._base_width, 0)

    def _add_action_button(self, text: str, fn: Callable[[], None]):
        btn = QPushButton(text)
        btn._original_text = text  # 保存原始文本
        btn._qt_start_handler = fn  # 保存原始处理函数
        btn.clicked.connect(fn)
        self.v.addWidget(MobileRow(btn))
        # 保存按钮引用以便同步状态
        if "出征" in text:
            self.btn_outing = btn
        return btn

    def _create_button(self, text: str, fn: Callable[[], None]) -> QPushButton:
        """创建按钮但不添加到布局"""
        btn = QPushButton(text)
        btn._original_text = text  # 保存原始文本
        btn._qt_start_handler = fn  # 保存原始处理函数
        btn.clicked.connect(fn)
        # 保存特定按钮的引用以便同步状态
        if "驻军" in text and "开始" in text:
            self.btn_garrison = btn
        elif "紧急治疗" in text:
            self.btn_emergency_heal = btn
        elif "打熊" in text:
            self.btn_bear = btn
        return btn

    def _sync_button_states(self):
        """同步移动界面按钮状态与主界面按钮状态"""
        try:
            t = self._tab()
            if t is None:
                return

            # 定义移动界面按钮与主界面按钮的映射
            button_mappings = [
                (self.btn_outing, getattr(t, "outing_btn", None)),
                (self.btn_garrison, getattr(getattr(t, "box_garrison", None), "btn", None) if hasattr(t, "box_garrison") else None),
                (self.btn_emergency_heal, getattr(t, "emergency_heal_btn", None)),
                (self.btn_bear, getattr(getattr(t, "box_bear", None), "btn", None) if hasattr(t, "box_bear") else None),
            ]

            for mobile_btn, main_btn in button_mappings:
                if mobile_btn is None or main_btn is None:
                    continue

                # 同步按钮文本
                main_text = main_btn.text()
                if mobile_btn.text() != main_text:
                    # 如果主界面按钮文本包含"停止"，说明任务正在运行
                    if "停止" in main_text:
                        # 移动界面按钮也显示"停止"
                        mobile_btn.setText(main_text)
                    else:
                        # 恢复原始文本
                        original_text = getattr(mobile_btn, "_original_text", None)
                        if original_text:
                            mobile_btn.setText(original_text)
                        else:
                            # 如果没有保存原始文本，使用主界面的文本
                            mobile_btn.setText(main_text)

                # 同步按钮启用状态
                if mobile_btn.isEnabled() != main_btn.isEnabled():
                    mobile_btn.setEnabled(main_btn.isEnabled())
        except Exception as e:
            # 静默失败，避免干扰正常操作
            pass

    def _display_name(self, serial: str) -> str:
        try:
            notes: Dict[str, str] = (self.app.cfg or {}).get("notes", {}) or {}
            alias = notes.get(serial)
            if alias:
                return f"{alias} ({serial})"
        except Exception:
            pass
        return serial

    def _update_global_mode_button(self):
        """更新全局模式按钮提示"""
        try:
            is_global = self.app.cfg.get("global_mode", False)
            if is_global:
                self.btn_global.setToolTip("全局模式: 开启")
                self.btn_global.setStyleSheet("background-color: #4CAF50;")  # 绿色表示开启
            else:
                self.btn_global.setToolTip("全局模式: 关闭")
                self.btn_global.setStyleSheet("")  # 默认颜色
        except Exception:
            pass

    # ---- device tab helpers ----
    def _tab(self):
        """获取当前选中的设备标签页（优先通过标签控件映射获取 serial）"""
        try:
            w = self.device_tabs.currentWidget()
            if w is not None:
                serial = self._widget_serial.get(w)
                if serial:
                    return getattr(self.app, "device_tabs", {}).get(serial)
        except Exception:
            pass
        # 兜底：按索引对应 app.device_tabs 的顺序
        current_index = self.device_tabs.currentIndex()
        if current_index < 0:
            return None
        serials = list(getattr(self.app, "device_tabs", {}).keys())
        if current_index >= len(serials):
            return None
        serial = serials[current_index]
        return getattr(self.app, "device_tabs", {}).get(serial)

    # ---- actions (proxy to main UI) ----
    def _safe_click(self, obj: Optional[QWidget], fallback: Optional[Callable[[], None]] = None):
        try:
            if obj is None:
                if fallback:
                    fallback()
                return
            h = getattr(obj, "_qt_start_handler", None)
            if callable(h):
                h()
            elif hasattr(obj, "click"):
                # type: ignore[attr-defined]
                obj.click()  # type: ignore
        except Exception:
            pass

    def _act_start_outing(self):
        """开始出征（根据选择的模式）"""
        t = self._tab()
        if t is None:
            return

        # 根据选择的模式设置主界面的参数
        if self.mode_army.isChecked():
            # 刷全军模式
            if hasattr(t, 'mode_army'):
                t.mode_army.setChecked(True)
            if hasattr(t, 'sweep_seconds'):
                t.sweep_seconds.setText(self.sweep_seconds.text())
            if hasattr(t, 'sweep_loops'):
                t.sweep_loops.setText(self.sweep_loops.text())
        else:
            # 刷王城模式
            if hasattr(t, 'mode_city'):
                t.mode_city.setChecked(True)
            if hasattr(t, 'city_target'):
                t.city_target.setCurrentIndex(self.city_target.currentIndex())
            if hasattr(t, 'city_heal_seconds'):
                t.city_heal_seconds.setText(self.city_heal_seconds.text())
            if hasattr(t, 'city_wait_seconds'):
                t.city_wait_seconds.setText(self.city_wait_seconds.text())

        # 点击开始按钮
        self._safe_click(getattr(t, "outing_btn", None))

    def _act_garrison(self):
        """自动驻军"""
        t = self._tab()
        if t is None:
            return

        # 设置驻军模式
        if hasattr(t, 'garrison_mode'):
            t.garrison_mode.setCurrentIndex(self.garrison_mode.currentIndex())

        self._safe_click(getattr(t, "garrison_btn", None))

    def _act_emergency_heal(self):
        """紧急治疗"""
        t = self._tab()
        if t is None:
            return
        self._safe_click(getattr(t, "emergency_heal_btn", None))

    def _act_ranshuang(self):
        """燃霜模式"""
        t = self._tab()
        if t is None:
            return
        self._safe_click(getattr(t, "ranshuang_btn", None))

    def _act_screenshot(self):
        """截图工具"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_tools", None)
        btn = getattr(box, "btn_shot", None) if box else None
        self._safe_click(btn)

    def _act_init_wild(self):
        """初始化到野外"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_tools", None)
        btn = getattr(box, "btn_init", None) if box else None
        self._safe_click(btn)

    def _act_withdraw(self):
        """一键撤军"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_tools", None)
        btn = getattr(box, "btn_withdraw", None) if box else None
        self._safe_click(btn)

    def _act_edit_coords(self):
        """编辑资源坐标"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_resources", None)
        btn = getattr(box, "btn_edit_coords", None) if box else None
        self._safe_click(btn)

    def _act_attack_resources(self):
        """打资源"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_resources", None)
        btn = getattr(box, "attack_btn", None) if box else None
        self._safe_click(btn)

    def _act_bear_mode(self):
        """启动打熊模式"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_bear", None)
        if box is None:
            return

        # 同步参数到主界面
        try:
            # 打熊时间
            time_val = self.bear_time.text().strip()
            if hasattr(box, "ed_time"):
                box.ed_time.setText(time_val)

            # 执行日
            day_text = self.bear_day.currentText()
            if hasattr(box, "cb_day"):
                idx = box.cb_day.findText(day_text)
                if idx >= 0:
                    box.cb_day.setCurrentIndex(idx)

            # 车头模式
            head_text = self.bear_head.currentText()
            if hasattr(box, "cb_head"):
                idx = box.cb_head.findText(head_text)
                if idx >= 0:
                    box.cb_head.setCurrentIndex(idx)

            # 发车间隔
            interval_val = self.bear_interval.text().strip()
            if hasattr(box, "ed_interval"):
                box.ed_interval.setText(interval_val)
        except Exception as e:
            print(f"同步打熊参数失败: {e}")

        # 点击按钮
        btn = getattr(box, "btn", None)
        self._safe_click(btn)

    def _act_close_help(self):
        """关闭上车"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_alliance", None)
        if box and hasattr(box, '_on_close_help'):
            try:
                box._on_close_help()
            except Exception as e:
                print(f"关闭上车失败: {e}")

    def _act_open_help(self):
        """打开上车"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_alliance", None)
        if box and hasattr(box, '_on_open_help'):
            try:
                box._on_open_help()
            except Exception as e:
                print(f"打开上车失败: {e}")

    def _act_auto_like(self):
        """自动点赞"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_alliance", None)
        btn = getattr(box, "btn_like", None) if box else None
        self._safe_click(btn)

    def _act_fast_join(self):
        """秒进集结"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_alliance", None)
        btn = getattr(box, "btn_fast", None) if box else None
        self._safe_click(btn)

    def _act_rank4(self):
        """一键四阶"""
        t = self._tab()
        if t is None:
            return
        box = getattr(t, "box_alliance", None)
        btn = getattr(box, "btn_rank4", None) if box else None
        self._safe_click(btn)

    # ---- global actions ----
    def _on_speed_changed(self, text: str):
        """速度因子变化"""
        try:
            if hasattr(self.app, 'speed_factor_input'):
                self.app.speed_factor_input.setText(text)
            if hasattr(self.app, 'on_speed_factor_changed'):
                self.app.on_speed_factor_changed(text)
        except Exception as e:
            print(f"设置速度因子失败: {e}")

    def _act_auto_connect_mumu(self):
        """自动连接MuMu模拟器"""
        try:
            if hasattr(self.app, 'auto_connect_mumu'):
                self.app.auto_connect_mumu()
        except Exception as e:
            print(f"自动连接MuMu失败: {e}")

    def _act_toggle_topmost(self):
        """切换窗口置顶（仅针对移动界面窗口）"""
        try:
            # 获取移动界面窗口
            window = None
            # 尝试从app获取移动窗口
            if hasattr(self.app, 'mobile_window') and self.app.mobile_window:
                window = self.app.mobile_window
            # 或者向上查找父窗口
            else:
                parent = self.parent()
                while parent:
                    if isinstance(parent, QMainWindow):
                        window = parent
                        break
                    parent = parent.parent()

            if window is None:
                print("未找到移动界面窗口")
                return

            # 获取当前窗口标志
            current_flags = window.windowFlags()

            # 切换置顶状态
            if current_flags & Qt.WindowStaysOnTopHint:
                # 当前是置顶，取消置顶
                # 保留其他标志，只移除置顶标志
                new_flags = current_flags & ~Qt.WindowStaysOnTopHint
                window.setWindowFlags(new_flags)
                self.btn_topmost.setText("📌 置顶")
                topmost_on = False
            else:
                # 当前不是置顶，设置置顶
                # 保留其他标志，添加置顶标志
                new_flags = current_flags | Qt.WindowStaysOnTopHint
                window.setWindowFlags(new_flags)
                self.btn_topmost.setText("📌 取消置顶")
                topmost_on = True

            # 同步所有已分离窗口的置顶状态
            try:
                for w in list(self._detached_windows.values()):
                    if w is None:
                        continue
                    flags = w.windowFlags()
                    if topmost_on:
                        w.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
                    else:
                        w.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
                    w.show()
            except Exception:
                pass

            # 重新显示窗口（setWindowFlags会隐藏窗口）
            window.show()

        except Exception as e:
            print(f"切换窗口置顶失败: {e}")
            import traceback
            traceback.print_exc()

    def _act_toggle_global_mode(self):
        """切换全局操作模式"""
        try:
            # 切换配置
            current = self.app.cfg.get("global_mode", False)
            self.app.cfg["global_mode"] = not current
            if hasattr(self.app, 'config_mgr'):
                self.app.config_mgr.save(self.app.cfg)

            # 更新按钮文本
            self._update_global_mode_button()

            # 打印提示
            print(f"全局操作模式: {'开启' if not current else '关闭'}")
        except Exception as e:
            print(f"切换全局操作模式失败: {e}")

    def _act_stop_all(self):
        """停止所有任务"""
        try:
            if hasattr(self.app, 'stop_all_now'):
                self.app.stop_all_now()
        except Exception as e:
            print(f"停止所有任务失败: {e}")

    # ---- tab detach/reattach (double-click) ----
    def _on_tab_bar_double_clicked(self, index: int) -> None:
        try:
            if index < 0:
                return
            w = self.device_tabs.widget(index)
            if not w:
                return
            serial = self._widget_serial.get(w)
            if not serial:
                return
            self._detach_tab(serial)
        except Exception:
            pass

    def _short_tab_name(self, serial: str) -> str:
        name = self._display_name(serial)
        if "(" in name:
            return name.split("(")[0].strip()
        return serial[:8] + "..." if len(serial) > 8 else serial

    def _detach_tab(self, serial: str) -> None:
        try:
            w = self.device_tab_widgets.get(serial)
            if not w:
                return
            idx = self.device_tabs.indexOf(w)
            if idx >= 0:
                self.device_tabs.removeTab(idx)
            # 若已分离则召回现有窗口
            wnd_existing = self._detached_windows.get(serial)
            if wnd_existing is not None:
                try:
                    wnd_existing.show(); wnd_existing.raise_(); wnd_existing.activateWindow()
                    return
                except Exception:
                    pass
            # 使用一个新的移动界面窗口承载完整内容，而不是空标签占位
            from .mobile_view_qt_new import MobileMainWindow
            wnd = MobileMainWindow(self.app)
            # 标题显示该设备名
            try:
                wnd.setWindowTitle(self._display_name(serial))
            except Exception:
                pass
            # 继承置顶状态（与当前窗口一致）
            try:
                if self.window() and (self.window().windowFlags() & Qt.WindowStaysOnTopHint):
                    wnd.setWindowFlags(wnd.windowFlags() | Qt.WindowStaysOnTopHint)
            except Exception:
                pass
            # 选择并仅保留该设备的标签
            try:
                tabs = wnd._content.device_tabs
                # 找到目标widget并选中
                target_widget = None
                for i in range(tabs.count() - 1, -1, -1):
                    wi = tabs.widget(i)
                    ser = getattr(wnd._content, "_widget_serial", {}).get(wi)
                    if ser == serial:
                        target_widget = wi
                    else:
                        tabs.removeTab(i)
                if target_widget is not None:
                    tabs.setCurrentWidget(target_widget)
            except Exception:
                pass
            # 记录窗口并绑定关闭回贴
            self._detached_windows[serial] = wnd
            def on_close(event):
                try:
                    self._reattach_tab(serial)
                finally:
                    event.accept()
            wnd.closeEvent = on_close  # type: ignore[assignment]
            try:
                wnd.destroyed.connect(lambda *_: self._reattach_tab(serial))
            except Exception:
                pass
            wnd.show(); wnd.raise_(); wnd.activateWindow()
        except Exception:
            pass

    def _reattach_tab(self, serial: str) -> None:
        try:
            wnd = self._detached_windows.pop(serial, None)
            w = None
            if wnd is not None:
                w = wnd.centralWidget()
                wnd.setCentralWidget(None)
                try:
                    wnd.deleteLater()
                except Exception:
                    pass
            if w is None:
                w = self.device_tab_widgets.get(serial)
            if w is None:
                return
            title = self._short_tab_name(serial)
            self.device_tabs.addTab(w, title)
            try:
                w.show()
            except Exception:
                pass
        except Exception:
            pass


# ---------------- Main Window ----------------
class MobileMainWindow(QMainWindow):
    """Mobile-style UI using a zoomable scene.

    Requirements implemented:
    - Base content 480x1280; zoom scales whole content (image-like)
    - Drag to pan; wheel scroll; Ctrl+Wheel zoom
    - No log area; content grows downward with clear separators
    - Actions directly proxy to main UI (equivalent operations)
    """

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("📱 移动界面")
        self.resize(400, 800)  # default window size (修改为400x800)

        # 保存窗口引用到app
        if hasattr(app, 'mobile_window'):
            app.mobile_window = self

        self._build()

    def _build(self) -> None:
        # Toolbar
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)
        act_in = QAction("🔍+", self); act_out = QAction("🔍-", self); act_100 = QAction("100%", self)
        tb.addAction(act_in); tb.addAction(act_out); tb.addAction(act_100)

        # Scene/View with fixed-width content
        self._content = MobileContentWidget(self.app)
        scene = QGraphicsScene(self)
        proxy: QGraphicsProxyWidget = scene.addWidget(self._content)
        proxy.setPos(0, 0)
        scene.setSceneRect(QRectF(0, 0, self._content.sizeHint().width(), max(self._content.sizeHint().height(), 1280)))

        self.view = ZoomableGraphicsView(scene, self)
        self.setCentralWidget(self.view)

        act_in.triggered.connect(self.view.zoom_in)
        act_out.triggered.connect(self.view.zoom_out)
        act_100.triggered.connect(self.view.zoom_reset)

        # allow scrolling and panning by default
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)

    # keep default closeEvent to allow AppQt wrapper to hook and restore main UI

