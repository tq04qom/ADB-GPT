from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QGroupBox, QRadioButton, QGridLayout, QComboBox, QDialog, QSplitter, QSizePolicy
)

from ..common.logger import Logger
from ..common.task_context import TaskContext
from ..common.worker import DeviceWorker
from ..core.adb import AdbClient

# 业务任务（沿用 v1.14 的实现）
from ..ui.tasks.sweep_army import run_sweep_army
from ..ui.tasks.sweep_fort import run_sweep_fort
from ..ui.tasks.auto_garrison import run_auto_garrison
from ..ui.tasks.emergency_heal import run_emergency_heal
from ..ui.tasks.init_heal import run_init_heal

# 扩展面板（联盟、打熊、打野、工具）
from .device_tab_extras_qt import HuntBox, BearModeBox, AllianceBox, ToolsBox, ResourcesBox


class _UiSignal(QObject):
    reset_button = Signal(object, str)  # (QPushButton, original_text)
    device_log = Signal(str)
    toast = Signal(str)


class DeviceTabQt(QWidget):
    """
    Qt 设备页签（首批迁移，覆盖核心功能）：
    - 出征+治疗：刷全军 / 王城/炮台（参数 + 开始/停止）
    - 自动驻军 + 紧急治疗
    - 设备标题状态 + 设备日志透传
    """

    def __init__(self, app, serial: str):
        super().__init__(parent=app)
        self.app = app  # type: ignore
        self.serial = serial
        self.logger: Logger = app.logger
        self.adb: AdbClient = app.adb
        self.worker: Optional[DeviceWorker] = app.workers.get(serial)

        self._sig = _UiSignal()
        self._sig.reset_button.connect(self._on_reset_button)
        self._sig.device_log.connect(lambda m: self.app.append_device_log(self.serial, m))
        self._sig.toast.connect(self._on_toast)

        # 同设备同任务互斥：记录正在运行的任务ID
        self._running_tasks = set()

        self._build_ui()
        self._load_sweep_army_config()  # 加载刷全军配置
        self.refresh_status()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 头部标题
        self.title_label = QLabel(f"设备：{self.serial}（离线）")
        root.addWidget(self.title_label)

        # 功能分组改为子标签，显著减少竖向占用
        from PySide6.QtWidgets import QTabWidget
        self.func_tabs = QTabWidget()
        # 延后添加到根布局：与小工具一起放入可调节分割器

        # 出征页
        outing_page = QWidget()
        outing_v = QVBoxLayout(outing_page)

        outing_box = QGroupBox("出征+治疗")
        outing_v.addWidget(outing_box)
        grid = QGridLayout(outing_box)
        grid.setColumnStretch(1, 1)

        # 任务类型
        grid.addWidget(QLabel("任务类型"), 0, 0)
        self.mode_army = QRadioButton("刷全军")
        self.mode_city = QRadioButton("刷王城")
        self.mode_army.setChecked(True)
        self.mode_army.toggled.connect(self._update_outing_mode)
        self.mode_city.toggled.connect(self._update_outing_mode)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode_army)
        mode_row.addWidget(self.mode_city)
        mode_wrap = QWidget(); mode_wrap.setLayout(mode_row)
        grid.addWidget(mode_wrap, 0, 1, 1, 3)

        # 刷全军参数面板
        self.army_panel = QWidget()
        army_grid = QGridLayout(self.army_panel)
        army_grid.setContentsMargins(0, 0, 0, 0)
        army_grid.addWidget(QLabel("停止时间(北京时间)"), 0, 0)
        self.sweep_stop_time = QLineEdit("7:00"); self.sweep_stop_time.setMinimumWidth(50); self.sweep_stop_time.setMaximumWidth(100)
        self.sweep_stop_time.setPlaceholderText("HH:MM")
        self.sweep_stop_time.textChanged.connect(self._save_sweep_army_config)  # 保存配置
        army_grid.addWidget(self.sweep_stop_time, 0, 1)
        army_grid.addWidget(QLabel("单次治疗数量"), 0, 2)
        self.sweep_heal_count = QLineEdit("1800"); self.sweep_heal_count.setMinimumWidth(50); self.sweep_heal_count.setMaximumWidth(100)
        self.sweep_heal_count.textChanged.connect(self._save_sweep_army_config)  # 保存配置
        army_grid.addWidget(self.sweep_heal_count, 0, 3)
        army_grid.addWidget(QLabel("循环次数"), 1, 0)
        self.sweep_loops = QLineEdit("999"); self.sweep_loops.setMinimumWidth(50); self.sweep_loops.setMaximumWidth(100)
        self.sweep_loops.textChanged.connect(self._save_sweep_army_config)  # 保存配置
        army_grid.addWidget(self.sweep_loops, 1, 1)
        army_grid.addWidget(QLabel("单次治疗时长(s)"), 1, 2)
        self.sweep_seconds = QLineEdit("15"); self.sweep_seconds.setMinimumWidth(50); self.sweep_seconds.setMaximumWidth(100)
        self.sweep_seconds.textChanged.connect(self._save_sweep_army_config)  # 保存配置
        army_grid.addWidget(self.sweep_seconds, 1, 3)
        army_grid.addWidget(QLabel("间隔(s)"), 2, 0)
        self.sweep_step_delay = QLineEdit("0.3"); self.sweep_step_delay.setMinimumWidth(60); self.sweep_step_delay.setMaximumWidth(120)
        self.sweep_step_delay.textChanged.connect(self._save_sweep_army_config)  # 保存配置
        army_grid.addWidget(self.sweep_step_delay, 2, 1)
        grid.addWidget(self.army_panel, 1, 0, 1, 4)

        # 刷王城参数面板
        self.city_panel = QWidget()
        city_grid = QGridLayout(self.city_panel)
        city_grid.setContentsMargins(0, 0, 0, 0)

        # 目标选择（单选）
        city_grid.addWidget(QLabel("目标"), 0, 0)
        self.city_target = QComboBox()
        self.city_target.addItems(["北地炮台", "西城炮台", "南翼炮台", "东城炮台", "太阳城"])
        city_grid.addWidget(self.city_target, 0, 1, 1, 3)

        # 队列类别（单选）
        city_grid.addWidget(QLabel("队列类别"), 1, 0)
        self.city_queue_default = QRadioButton("默认队列")
        self.city_queue_12 = QRadioButton("1队+2队")
        self.city_queue_default.setChecked(True)
        queue_row = QHBoxLayout()
        queue_row.addWidget(self.city_queue_default)
        queue_row.addWidget(self.city_queue_12)
        queue_row.addStretch()
        queue_wrap = QWidget(); queue_wrap.setLayout(queue_row)
        city_grid.addWidget(queue_wrap, 1, 1, 1, 3)

        # 治疗时长
        city_grid.addWidget(QLabel("治疗时长(秒)"), 2, 0)
        self.city_heal_seconds = QLineEdit("8")
        self.city_heal_seconds.setMinimumWidth(50); self.city_heal_seconds.setMaximumWidth(100)
        city_grid.addWidget(self.city_heal_seconds, 2, 1)

        # 治疗后等待时长
        city_grid.addWidget(QLabel("等待时长(秒)"), 2, 2)
        self.city_wait_seconds = QLineEdit("0")
        self.city_wait_seconds.setMinimumWidth(50); self.city_wait_seconds.setMaximumWidth(100)
        city_grid.addWidget(self.city_wait_seconds, 2, 3)

        # 循环间隔等待
        city_grid.addWidget(QLabel("循环间隔(秒)"), 3, 0)
        self.city_loop_interval = QLineEdit("0")
        self.city_loop_interval.setMinimumWidth(50); self.city_loop_interval.setMaximumWidth(100)
        city_grid.addWidget(self.city_loop_interval, 3, 1)

        # 伤兵图标坐标
        city_grid.addWidget(QLabel("伤兵坐标"), 4, 0)
        self.city_soldier_coord = QComboBox()
        self.city_soldier_coord.addItems(["(556, 1044)", "(554, 949)", "(556, 840)"])
        self.city_soldier_coord.setCurrentIndex(0)  # 默认选择第一个
        city_grid.addWidget(self.city_soldier_coord, 4, 1)

        grid.addWidget(self.city_panel, 1, 0, 1, 4)
        self.city_panel.hide()  # 默认隐藏

        # 初始化治疗面板
        init_heal_panel = QWidget()
        init_heal_layout = QHBoxLayout(init_heal_panel)
        init_heal_layout.setContentsMargins(0, 0, 0, 0)
        self.init_heal_btn = QPushButton("初始化治疗")
        self.init_heal_btn._qt_start_handler = self._btn_init_heal
        self.init_heal_btn.clicked.connect(self._btn_init_heal)
        init_heal_layout.addWidget(self.init_heal_btn)
        init_heal_layout.addWidget(QLabel("单次治疗数量"))
        self.init_heal_count = QLineEdit("999"); self.init_heal_count.setMinimumWidth(50); self.init_heal_count.setMaximumWidth(100)
        init_heal_layout.addWidget(self.init_heal_count)
        init_heal_layout.addStretch()
        grid.addWidget(init_heal_panel, 3, 0, 1, 4)

        # 开始按钮
        self.outing_btn = QPushButton("开始刷全军")
        self.outing_btn._qt_start_handler = self._btn_outing
        self.outing_btn.clicked.connect(self._btn_outing)
        grid.addWidget(self.outing_btn, 4, 0, 1, 4)

        # 移除纵向拉伸以减少页面高度和滚动距离
        self.func_tabs.addTab(outing_page, "出征")

        # 驻军页
        garrison_page = QWidget()
        garrison_v = QVBoxLayout(garrison_page)

        # 驻军模块
        gar_box = QGroupBox("自动驻军/治疗")
        garrison_v.addWidget(gar_box)
        gar = QHBoxLayout(gar_box)
        gar.addWidget(QLabel("驻军模式"))
        self.garrison_mode = QComboBox(); self.garrison_mode.addItems(["乔伊", "收菜"])  # joy/harvest
        gar.addWidget(self.garrison_mode)
        self.garrison_btn = QPushButton("开始自动驻军")
        self.garrison_btn._qt_start_handler = self._btn_auto_garrison
        self.garrison_btn.clicked.connect(self._btn_auto_garrison)
        gar.addWidget(self.garrison_btn)
        self.emergency_heal_btn = QPushButton("紧急治疗")
        self.emergency_heal_btn._qt_start_handler = self._btn_emergency_heal
        self.emergency_heal_btn.clicked.connect(self._btn_emergency_heal)
        gar.addWidget(self.emergency_heal_btn)

        # 燃霜模块（在驻军下一行）
        ranshuang_box = QGroupBox("燃霜模式")
        garrison_v.addWidget(ranshuang_box)
        ranshuang_h = QHBoxLayout(ranshuang_box)
        self.ranshuang_btn = QPushButton("开始燃霜模式")
        self.ranshuang_btn._qt_start_handler = self._btn_ranshuang
        self.ranshuang_btn.clicked.connect(self._btn_ranshuang)
        ranshuang_h.addWidget(self.ranshuang_btn)

        # 添加拉伸以保持紧凑
        garrison_v.addStretch()

        # 移除横向/纵向多余拉伸，保持紧凑
        self.func_tabs.addTab(garrison_page, "驻军")

        # 其他功能页签（工具改为常显，不放入页签）
        self.func_tabs.addTab(AllianceBox(self), "联盟")
        self.func_tabs.addTab(BearModeBox(self), "打熊")
        self.func_tabs.addTab(HuntBox(self), "打野")
        self.func_tabs.addTab(ResourcesBox(self), "资源")

        # 小工具：常显（与功能子页放入可调垂直分割器，支持用户拉伸并记忆尺寸）
        try:
            tools_box = ToolsBox(self)
            try:
                tools_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
                tools_box.setMinimumHeight(1)
            except Exception:
                pass
        except Exception:
            tools_box = QWidget()
        self.inner_splitter = QSplitter(Qt.Vertical)
        self.inner_splitter.setChildrenCollapsible(True)
        self.inner_splitter.addWidget(self.func_tabs)
        self.inner_splitter.addWidget(tools_box)
        self.inner_splitter.setStretchFactor(0, 4)
        self.inner_splitter.setStretchFactor(1, 1)
        # 初始高度（从配置读取），顶部为功能子页，底部为小工具
        try:
            top_h = int(self.app.cfg.get("qt_tab_top_h", 800))
            bottom_h = int(self.app.cfg.get("qt_tab_tools_h", 160))
            self.inner_splitter.setSizes([max(120, top_h), max(60, bottom_h)])
        except Exception:
            pass
        root.addWidget(self.inner_splitter, 1)
        # 横向间隙：按需求改为默认最小（0），且不再提供调整入口
        self._h_spacing = 0
        # 收集需要应用横向间隙的布局对象
        self._hspace_layouts = [grid, army_grid, city_grid, gar, mode_row]
        self._apply_horizontal_spacing()

        # 拖动时即时保存到配置
        def _save_sizes():
            try:
                sizes = self.inner_splitter.sizes()
                if sizes and len(sizes) >= 2:
                    self.app.cfg["qt_tab_top_h"] = sizes[0]
                    self.app.cfg["qt_tab_tools_h"] = sizes[1]
                    cfg_mgr = getattr(self.app, "config_mgr", None)
                    if cfg_mgr is not None:
                        cfg_mgr.save(self.app.cfg)
            except Exception:
                pass
        self.inner_splitter.splitterMoved.connect(lambda *_: _save_sizes())

        # 加载保存的配置
        self._load_city_config()
        # 加载保存的配置
        self._load_city_config()

    # ---------------- 公共 ----------------

    def _load_city_config(self):
        """加载刷王城的配置（按设备分别存储）"""
        try:
            # 获取设备特定的配置键前缀
            device_prefix = f"city_{self.serial}_"

            # 加载目标
            saved_target = self.app.cfg.get(f"{device_prefix}target", "北地炮台")
            idx = self.city_target.findText(saved_target)
            if idx >= 0:
                self.city_target.setCurrentIndex(idx)

            # 加载队列模式
            saved_queue = self.app.cfg.get(f"{device_prefix}queue_mode", "default")
            if saved_queue == "team12":
                self.city_queue_12.setChecked(True)
            else:
                self.city_queue_default.setChecked(True)

            # 加载时间参数
            heal_secs = self.app.cfg.get(f"{device_prefix}heal_seconds", 8)
            self.city_heal_seconds.setText(str(heal_secs))

            wait_secs = self.app.cfg.get(f"{device_prefix}wait_seconds", 0)
            self.city_wait_seconds.setText(str(wait_secs))

            loop_interval = self.app.cfg.get(f"{device_prefix}loop_interval", 0)
            self.city_loop_interval.setText(str(loop_interval))

            # 加载伤兵坐标
            soldier_coord = self.app.cfg.get(f"{device_prefix}soldier_coord", "(556, 1044)")
            idx = self.city_soldier_coord.findText(soldier_coord)
            if idx >= 0:
                self.city_soldier_coord.setCurrentIndex(idx)
        except Exception:
            pass
    def refresh_status(self) -> None:
        online = self.serial in self.app.workers
        self.title_label.setText(f"设备：{self.serial}（{'在线' if online else '离线'}）")
        self.worker = self.app.workers.get(self.serial)

    def device_log(self, msg: str) -> None:
        self._sig.device_log.emit(msg)

    def _toast(self, text: str) -> None:
        # 通过信号切回主线程再创建对话框，避免 QObject::setParent/QTimer 线程报错
        self._sig.toast.emit(text)

    # ---------------- 任务封装 ----------------
    def _start_task_with_button(self, task_id: str, button: QPushButton, runner: Callable[[Callable[[], bool]], None]):
        if self.serial not in self.app.workers:
            self._toast("设备不在线，无法执行")
            return
        # 并发互斥：同设备同任务ID只允许一个实例
        if task_id in self._running_tasks:
            self._toast(f"任务 {task_id} 正在运行，请稍候…")
            return
        stop_attr = f"_{task_id}_stop_ev"
        stop_event = threading.Event()
        setattr(self, stop_attr, stop_event)

        def should_stop() -> bool:
            ev = getattr(self, stop_attr, stop_event)
            return ev.is_set()

        # 切换按钮到停止状态
        original_text = button.text()
        button.setProperty("_original_text", original_text)
        button.setProperty("_running_task_id", task_id)
        button.setText(f"停止{original_text}")
        def _stop():
            try:
                stop_event.set()
                button.setEnabled(False)
                self._toast("已发送停止指令")
            except Exception:
                pass
        try:
            # 重新绑定点击为停止
            button.clicked.disconnect()
        except Exception:
            pass
        button.clicked.connect(_stop)

        # 记录正在运行任务
        self._running_tasks.add(task_id)

        def task_wrapper():
            try:
                runner(should_stop)
            finally:
                # 回到主线程恢复按钮
                self._sig.reset_button.emit(button, original_text)

        # 调试：检查 worker 是否存在
        worker = self.app.workers.get(self.serial)
        if worker is None:
            print(f"[ERROR] Worker 不存在: {self.serial}")
            print(f"[DEBUG] app.workers 内容: {list(self.app.workers.keys())}")
            self._toast(f"错误：设备 {self.serial} 的工作线程不存在")
            self._sig.reset_button.emit(button, original_text)
            return

        print(f"[DEBUG] 提交任务到 worker: {self.serial}, task_id={task_id}")
        worker.submit(task_wrapper)

    def _on_reset_button(self, button: QPushButton, original_text: str):
        try:
            # 解除互斥标记
            task_id = button.property("_running_task_id")
            if task_id:
                try:
                    self._running_tasks.discard(task_id)
                except Exception:
                    pass
                button.setProperty("_running_task_id", None)
            button.setEnabled(True)
            try:
                button.clicked.disconnect()
            except Exception:
                pass
            # 恢复原始点击逻辑
            handler = getattr(button, "_qt_start_handler", None)
            if callable(handler):
                button.clicked.connect(handler)
            else:
                if button is self.outing_btn:
                    button.clicked.connect(self._btn_outing)
                elif button is self.garrison_btn:
                    button.clicked.connect(self._btn_auto_garrison)
                elif button is self.emergency_heal_btn:
                    button.clicked.connect(self._btn_emergency_heal)
                elif button is self.ranshuang_btn:
                    button.clicked.connect(self._btn_ranshuang)
            button.setText(original_text)
        except Exception:
            pass

    def _on_toast(self, text: str):
        """
        无声提示：非阻塞弹层，3秒后自动关闭
        """
        try:
            dlg = QDialog(self)
            dlg.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            dlg.setAttribute(Qt.WA_TranslucentBackground, True)
            lay = QVBoxLayout(dlg)
            lab = QLabel(text)
            lab.setStyleSheet("QLabel { background: rgba(30,30,30,200); color:#eee; border-radius:6px; padding:10px 14px; }")
            lay.addWidget(lab)
            dlg.adjustSize()
            # 放在当前页右下角附近
            g = self.geometry()
            pos = self.mapToGlobal(g.bottomRight())
            dlg.move(pos.x() - dlg.width() - 20, pos.y() - dlg.height() - 20)
            dlg.show()
            QTimer.singleShot(3000, dlg.close)
        except Exception:
            pass

    # ---------------- 按钮回调 ----------------
    def stop_all_tasks_immediately(self) -> None:
        try:
            for task_id in list(self._running_tasks):
                try:
                    ev = getattr(self, f"_{task_id}_stop_ev", None)
                    if ev is not None:
                        ev.set()
                except Exception:
                    pass
        except Exception:
            pass

    def _update_outing_mode(self):
        """切换刷全军/刷王城模式时，显示/隐藏对应参数面板"""
        try:
            if self.mode_army.isChecked():
                self.army_panel.show()
                self.city_panel.hide()
                self.outing_btn.setText("开始刷全军")
            else:
                self.army_panel.hide()
                self.city_panel.show()
                self.outing_btn.setText("开始刷王城")
        except Exception:
            pass

    def _btn_outing(self):
        if self.mode_army.isChecked():
            self._btn_sweep_army()
        else:
            self._btn_sweep_city()

    def _task_context(self, target_tab: "DeviceTabQt", should_stop, *, threshold=None, verbose=False) -> TaskContext:
        return TaskContext(
            app=self.app,
            serial=target_tab.serial,
            toast=target_tab._toast,
            log=target_tab.device_log,
            should_stop=should_stop,
            threshold=threshold,
            verbose=verbose,
        )

    def _btn_sweep_army(self):
        try:
            secs = int(self.sweep_seconds.text().strip() or "9")
        except Exception:
            secs = 9
        try:
            loops = int(self.sweep_loops.text().strip() or "1")
        except Exception:
            loops = 1
        try:
            step_delay = float(self.sweep_step_delay.text().strip() or "0.10")
        except Exception:
            step_delay = 0.10

        # 获取停止时间（北京时间）
        stop_time = self.sweep_stop_time.text().strip() or "7:00"

        # 获取单次治疗数量
        try:
            heal_count = int(self.sweep_heal_count.text().strip() or "1800")
        except Exception:
            heal_count = 1800

        def make_runner(tab: "DeviceTabQt"):
            def runner(should_stop):
                ctx = self._task_context(tab, should_stop, threshold=None, verbose=False)
                run_sweep_army(
                    ctx.app, ctx.serial, secs,
                    toast=ctx.toast, log=ctx.log,
                    loop_count=loops,
                    total_duration=0,
                    should_stop=ctx.should_stop,
                    step_delay=step_delay,
                    threshold=ctx.threshold,
                    verbose=ctx.verbose,
                    stop_time=stop_time,
                    heal_count=heal_count,
                )
            return runner

        # 刷全军不受全局操作模式控制，只能独立操作当前设备
        self._start_task_with_button("sweep", self.outing_btn, make_runner(self))

    def _btn_sweep_city(self):
        """刷王城按钮处理"""
        from ..ui.tasks.sweep_city import run_sweep_city

        # 获取目标
        target_text = self.city_target.currentText()
        target_map = {
            "北地炮台": "north",
            "西城炮台": "west",
            "南翼炮台": "south",
            "东城炮台": "east",
            "太阳城": "sun"
        }
        target = target_map.get(target_text, "north")

        # 获取队列模式
        queue_mode = "default" if self.city_queue_default.isChecked() else "team12"

        # 获取时间参数
        try:
            heal_seconds = int(self.city_heal_seconds.text().strip() or "8")
        except Exception:
            heal_seconds = 8
        try:
            wait_seconds = int(self.city_wait_seconds.text().strip() or "0")
        except Exception:
            wait_seconds = 0
        try:
            loop_interval = int(self.city_loop_interval.text().strip() or "0")
        except Exception:
            loop_interval = 0

        # 获取伤兵坐标
        soldier_coord_str = self.city_soldier_coord.currentText()
        # 解析坐标字符串 "(556, 1044)" -> (556, 1044)
        try:
            coord_parts = soldier_coord_str.strip("()").split(",")
            soldier_x = int(coord_parts[0].strip())
            soldier_y = int(coord_parts[1].strip())
        except Exception:
            soldier_x, soldier_y = 556, 1044

        # 保存配置到app.cfg以便下次记住（按设备分别存储）
        device_prefix = f"city_{self.serial}_"
        self.app.cfg[f"{device_prefix}target"] = target_text
        self.app.cfg[f"{device_prefix}queue_mode"] = queue_mode
        self.app.cfg[f"{device_prefix}heal_seconds"] = heal_seconds
        self.app.cfg[f"{device_prefix}wait_seconds"] = wait_seconds
        self.app.cfg[f"{device_prefix}loop_interval"] = loop_interval
        self.app.cfg[f"{device_prefix}soldier_coord"] = soldier_coord_str

        def make_runner(tab: "DeviceTabQt"):
            def runner(should_stop):
                ctx = self._task_context(tab, should_stop, threshold=None, verbose=False)
                run_sweep_city(
                    ctx.app, ctx.serial,
                    target=target,
                    queue_mode=queue_mode,
                    heal_seconds=heal_seconds,
                    wait_seconds=wait_seconds,
                    loop_interval=loop_interval,
                    soldier_x=soldier_x,
                    soldier_y=soldier_y,
                    toast=ctx.toast,
                    log=ctx.log,
                    should_stop=ctx.should_stop,
                    threshold=ctx.threshold,
                    verbose=ctx.verbose,
                )
            return runner

        if bool(self.app.cfg.get("global_mode", False)):
            for tab in list(self.app.device_tabs.values()):
                tab._start_task_with_button("city", tab.outing_btn, make_runner(tab))
        else:
            self._start_task_with_button("city", self.outing_btn, make_runner(self))

    def _btn_auto_garrison(self):
        raw = self.garrison_mode.currentText()
        mode = "joy" if raw in ("乔伊", "joy") else "harvest"
        def make_runner(tab: "DeviceTabQt"):
            def runner(should_stop):
                ctx = self._task_context(tab, should_stop, threshold=None, verbose=False)
                run_auto_garrison(
                    ctx.app, ctx.serial, mode,
                    toast=ctx.toast, log=ctx.log,
                    should_stop=ctx.should_stop,
                    threshold=ctx.threshold,
                    verbose=ctx.verbose,
                )
            return runner
        if bool(self.app.cfg.get("global_mode", False)):
            for tab in list(self.app.device_tabs.values()):
                tab._start_task_with_button("garrison", tab.garrison_btn, make_runner(tab))
        else:
            self._start_task_with_button("garrison", self.garrison_btn, make_runner(self))

    def _btn_emergency_heal(self):
        def make_runner(tab: "DeviceTabQt"):

            def runner(should_stop):
                ctx = self._task_context(tab, should_stop, threshold=None, verbose=False)
                run_emergency_heal(
                    ctx.app, ctx.serial,
                    toast=ctx.toast, log=ctx.log,
                    should_stop=ctx.should_stop,
                    threshold=ctx.threshold,
                    verbose=ctx.verbose,
                )
            return runner
        if bool(self.app.cfg.get("global_mode", False)):
            for tab in list(self.app.device_tabs.values()):
                tab._start_task_with_button("emergency_heal", tab.emergency_heal_btn, make_runner(tab))
        else:
            self._start_task_with_button("emergency_heal", self.emergency_heal_btn, make_runner(self))

    def _btn_init_heal(self):
        """初始化治疗按钮处理"""
        try:
            heal_count = int(self.init_heal_count.text().strip() or "999")
        except Exception:
            heal_count = 999

        def make_runner(tab: "DeviceTabQt"):
            def runner(should_stop):
                ctx = self._task_context(tab, should_stop)
                run_init_heal(
                    ctx.app, ctx.serial, heal_count,
                    toast=ctx.toast, log=ctx.log,
                    should_stop=ctx.should_stop,
                )
            return runner

        self._start_task_with_button("init_heal", self.init_heal_btn, make_runner(self))

    def _btn_ranshuang(self):
        from ..ui.tasks.ranshuang_mode import run_ranshuang_mode
        def make_runner(tab: "DeviceTabQt"):
            def runner(should_stop):
                ctx = self._task_context(tab, should_stop, threshold=None, verbose=False)
                run_ranshuang_mode(
                    ctx.app, ctx.serial,
                    toast=ctx.toast, log=ctx.log,
                    should_stop=ctx.should_stop,
                    threshold=ctx.threshold,
                    verbose=ctx.verbose,
                )
            return runner
        if bool(self.app.cfg.get("global_mode", False)):
            for tab in list(self.app.device_tabs.values()):
                tab._start_task_with_button("ranshuang", tab.ranshuang_btn, make_runner(tab))
        else:
            self._start_task_with_button("ranshuang", self.ranshuang_btn, make_runner(self))

    # ---------------- 横向间隙控制 ----------------
    def get_horizontal_spacing(self) -> int:
        try:
            return int(getattr(self, "_h_spacing", 6))
        except Exception:
            return 6

    def _apply_horizontal_spacing(self) -> None:
        try:
            sp = self.get_horizontal_spacing()
            for lay in getattr(self, "_hspace_layouts", []) or []:
                try:
                    if isinstance(lay, QHBoxLayout):
                        lay.setSpacing(sp)
                    elif isinstance(lay, QGridLayout):
                        # GridLayout 仅设置横向间距
                        lay.setHorizontalSpacing(sp)
                except Exception:
                    pass
        except Exception:
            pass

    def set_horizontal_spacing(self, value: int) -> None:
        try:
            value = int(value)
            value = max(0, min(40, value))
            self._h_spacing = value
            # 持久化到配置（按设备序列号区分）
            try:
                self.app.cfg[f"qt_h_space:{self.serial}"] = value
                cfg_mgr = getattr(self.app, "config_mgr", None)
                if cfg_mgr is not None:
                    cfg_mgr.save(self.app.cfg)
            except Exception:
                pass
            self._apply_horizontal_spacing()
        except Exception:
            pass

    def adjust_horizontal_spacing(self, delta: int) -> None:
        try:
            self.set_horizontal_spacing(self.get_horizontal_spacing() + int(delta))
        except Exception:
            pass

    # ============ 刷全军配置保存/加载 ============
    def _load_sweep_army_config(self) -> None:
        """从配置文件加载刷全军参数（按设备保存）"""
        try:
            # 按设备保存配置：sweep_army_config -> {serial -> {params}}
            sweep_config = self.app.cfg.get("sweep_army_config", {})
            device_config = sweep_config.get(self.serial, {})

            # 加载所有参数，使用设备特定配置或全局默认值
            sweep_seconds = device_config.get("sweep_seconds", "15")
            self.sweep_seconds.setText(str(sweep_seconds))

            sweep_stop_time = device_config.get("sweep_stop_time", "7:00")
            self.sweep_stop_time.setText(str(sweep_stop_time))

            sweep_heal_count = device_config.get("sweep_heal_count", "1800")
            self.sweep_heal_count.setText(str(sweep_heal_count))

            sweep_loops = device_config.get("sweep_loops", "999")
            self.sweep_loops.setText(str(sweep_loops))

            sweep_step_delay = device_config.get("sweep_step_delay", "0.3")
            self.sweep_step_delay.setText(str(sweep_step_delay))
        except Exception:
            pass

    def _save_sweep_army_config(self) -> None:
        """保存刷全军参数到配置文件（按设备保存）"""
        try:
            if not hasattr(self.app, "cfg"):
                return

            # 按设备保存配置：sweep_army_config -> {serial -> {params}}
            if "sweep_army_config" not in self.app.cfg:
                self.app.cfg["sweep_army_config"] = {}

            if self.serial not in self.app.cfg["sweep_army_config"]:
                self.app.cfg["sweep_army_config"][self.serial] = {}

            device_config = self.app.cfg["sweep_army_config"][self.serial]

            # 保存所有参数到设备特定配置
            device_config["sweep_seconds"] = self.sweep_seconds.text().strip()
            device_config["sweep_stop_time"] = self.sweep_stop_time.text().strip()
            device_config["sweep_heal_count"] = self.sweep_heal_count.text().strip()
            device_config["sweep_loops"] = self.sweep_loops.text().strip()
            device_config["sweep_step_delay"] = self.sweep_step_delay.text().strip()

            self.app.config_mgr.save(self.app.cfg)
        except Exception:
            pass
