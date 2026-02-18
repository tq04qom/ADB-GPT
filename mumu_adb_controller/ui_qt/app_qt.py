from __future__ import annotations

import os
import sys
import ctypes
from typing import Dict, Callable
import threading
import concurrent.futures as futures

import time


from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QSplitter, QPlainTextEdit,
    QTabWidget, QFrame, QCheckBox, QListWidget, QListWidgetItem,
    QGroupBox, QInputDialog, QScrollArea, QTabBar
)

from ..common.config import AppConfig
from ..common.logger import Logger
from ..core.adb import AdbClient
from ..common.worker import DeviceWorker
from .device_tab_qt import DeviceTabQt


class _LogEmitter(QObject):
    text_appended = Signal(str)


class _UiInvoker(QObject):
    invoked = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.invoked.connect(self._run_invoked)

    def _run_invoked(self, func: object) -> None:
        try:
            if callable(func):
                func()
        except Exception:
            pass


class AppQt(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("无尽辅助羽柔子开发威力加强版 V1.16 (Qt)")
        self.resize(1180, 780)
        # 允许窗口大幅缩小（适配功能页签化后的紧凑布局）
        # 最小宽度改为400，支持更窄的布局
        self.setMinimumSize(400, 480)

        # 配置/日志/ADB
        self.config_mgr = AppConfig(app_name="MuMuADBController")
        self.cfg: Dict = self.config_mgr.load() or {}

        self.logger = Logger()
        self._emitter = _LogEmitter()
        self._emitter.text_appended.connect(self._append_main_log)
        self.logger.set_sink(self._emitter.text_appended.emit)
        self._ui_invoker = _UiInvoker()

        self.workers: Dict[str, DeviceWorker] = {}
        self.device_tabs: Dict[str, DeviceTabQt] = {}
        self._detached_windows: Dict[str, QMainWindow] = {}

        self.adb = AdbClient(adb_path=self.cfg.get("adb_path"), logger=self.logger)

        # 构建 UI
        self._build_ui()
        # 应用置顶状态（启动即生效）
        try:
            if bool(self.cfg.get("always_on_top", False)):
                self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
                self.show()
        except Exception:
            pass


        # 首次刷新设备并构建标签页
        try:
            self.refresh_devices()
        except Exception:
            pass

        # 还原窗口几何
        try:
            geom = self.cfg.get("qt_geometry")
            if isinstance(geom, dict):
                self.setGeometry(
                    geom.get("x", 100), geom.get("y", 100),
                    geom.get("w", 1180), geom.get("h", 780)
                )
        except Exception:
            pass

        # 启动时自动连接 MuMu（可在“总览”页开关）
        try:
            if bool(self.cfg.get("auto_connect_on_start", True)):
                QTimer.singleShot(200, self.auto_connect_mumu)
        except Exception:
            pass

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        cw = QWidget(self)
        self.setCentralWidget(cw)
        root_v = QVBoxLayout(cw)
        root_v.setContentsMargins(8, 8, 8, 8)
        root_v.setSpacing(6)

        # 顶栏
        top = QHBoxLayout()
        top.setSpacing(6)
        root_v.addLayout(top)

        # 顶栏：全局操作模式 + 置顶（按钮）

        self.chk_global_mode = QCheckBox("全局操作模式")
        self.chk_global_mode.setChecked(bool(self.cfg.get("global_mode", False)))
        self.chk_global_mode.toggled.connect(self.toggle_global_mode)
        top.addWidget(self.chk_global_mode)

        # 速度因子（在全局模式右侧）
        top.addWidget(QLabel("速度"))
        self.speed_factor_input = QLineEdit("1.0")
        self.speed_factor_input.setFixedWidth(50)
        self.speed_factor_input.setToolTip("速度因子：1.0 = 100%，0.5 = 50%，2.0 = 200%")
        self.speed_factor_input.textChanged.connect(self.on_speed_factor_changed)
        top.addWidget(self.speed_factor_input)

        # 每个设备标签页的横向间隙快速调节（仅作用于当前设备页签）

        self.speed_factor = 1.0  # 初始化速度因子

        # 全局控制按钮（在速度因子右侧）：暂停所有 / 停止所有
        self.btn_pause_all = QPushButton("暂停所有")
        self.btn_pause_all.setCheckable(True)
        self.btn_pause_all.toggled.connect(self.toggle_pause_all)
        top.addWidget(self.btn_pause_all)

        self.btn_stop_all = QPushButton("停止所有")
        self.btn_stop_all.clicked.connect(self.stop_all_now)
        top.addWidget(self.btn_stop_all)

        top.addStretch(1)

        # 移动界面按钮
        self.btn_mobile_view = QPushButton("📱 移动界面")
        self.btn_mobile_view.clicked.connect(self.open_mobile_view)
        self.btn_mobile_view.setToolTip("打开移动端风格界面")
        top.addWidget(self.btn_mobile_view)

        # 置顶按钮移至最右侧
        self.btn_on_top = QPushButton("置顶")
        self.btn_on_top.setCheckable(True)
        self.btn_on_top.setChecked(bool(self.cfg.get("always_on_top", False)))
        self.btn_on_top.toggled.connect(self.toggle_always_on_top)
        top.addWidget(self.btn_on_top)

        # 移动界面窗口引用
        self.mobile_window = None

        # 全局暂停/停止事件
        self.pause_event = threading.Event()

        # 中部分割（左设备区 / 右工作区）
        splitter = QSplitter(Qt.Horizontal)
        root_v.addWidget(splitter, 1)

        # 左侧区域取消单独占用（设备列表移动到“欢迎”标签）
        # splitter 仅放置右侧主区域

        right = QWidget()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(4, 4, 4, 4)

        print("[DEBUG] _build_ui: 创建设备标签内容")
        # 顶部：设备标签内容
        self.nb_content = QTabWidget()
        self.nb_content.setTabPosition(QTabWidget.North)
        # 允许拖动标签（用于重排）；双击可分离到独立窗口
        try:
            self.nb_content.setMovable(True)
            if hasattr(self.nb_content, "tabBarDoubleClicked"):
                self.nb_content.tabBarDoubleClicked.connect(self._on_tab_bar_double_clicked)
        except Exception:
            pass
        print("[DEBUG] _build_ui: 创建总览页")
        # 总览页（原“欢迎”页）
        overview = QWidget()
        ov = QVBoxLayout(overview)
        ov.setContentsMargins(4, 4, 4, 4)
        ov.setSpacing(6)

        # 主布局：左侧（设备列表）+ 中间（预览）+ 右侧（控制面板）
        print("[DEBUG] _build_ui: 创建主布局")
        main_h = QHBoxLayout()

        # === 左侧：设备列表 ===
        print("[DEBUG] _build_ui: 创建设备列表")
        dev_box = QGroupBox("设备列表")
        dev_v = QVBoxLayout(dev_box)
        self.device_list = QListWidget()
        print("[DEBUG] _build_ui: 连接设备列表信号")
        self.device_list.itemClicked.connect(self._on_device_item_clicked)
        self.device_list.itemDoubleClicked.connect(self._on_device_item_double_clicked)
        dev_v.addWidget(self.device_list, 1)
        print("[DEBUG] _build_ui: 设备列表创建完成")

        # === 中间：预览框（9:16 比例，宽度 270px，高度 480px）===
        print("[DEBUG] _build_ui: 创建预览框")
        preview_box = QGroupBox("预览")
        preview_v = QVBoxLayout(preview_box)
        preview_v.setContentsMargins(4, 4, 4, 4)
        self.preview_label = QLabel("无预览")
        # 设置固定宽度 270px，最小高度 480px（9:16 比例）
        self.preview_label.setFixedWidth(180)  # 降低为原来的 2/3（更紧凑）
        self.preview_label.setMinimumHeight(480)
        self.preview_label.setStyleSheet("QLabel { background:#111; color:#bbb; border:1px solid #333; padding:6px; }")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setScaledContents(False)
        preview_v.addWidget(self.preview_label)
        preview_v.addStretch(1)
        print("[DEBUG] _build_ui: 预览框创建完成")

        # === 右侧：控制面板（垂直布局）===
        print("[DEBUG] _build_ui: 创建控制面板")
        right_panel = QWidget()
        right_panel_v = QVBoxLayout(right_panel)
        right_panel_v.setContentsMargins(0, 0, 0, 0)
        right_panel_v.setSpacing(6)

        # 连接控制（紧凑布局，不占满整行）
        print("[DEBUG] _build_ui: 创建连接控制")
        conn_box = QGroupBox("连接控制")
        conn_grid = QGridLayout(conn_box)
        conn_grid.setContentsMargins(6, 6, 6, 6)
        conn_grid.setSpacing(4)

        self.btn_auto_mumu = QPushButton("自动连接MuMu")
        self.btn_auto_mumu.clicked.connect(self.auto_connect_mumu)
        btn_manual = QPushButton("手动连接…")
        btn_manual.clicked.connect(self.connect_ip_port_dialog)
        btn_disconnect = QPushButton("断开选中")
        btn_disconnect.clicked.connect(self.disconnect_selected_device)
        btn_watch = QPushButton("掉线监控")
        btn_watch.setCheckable(True)
        btn_watch.toggled.connect(self.toggle_offline_watch)

        self.chk_auto_on_start = QCheckBox("启动时自动连接")
        self.chk_auto_on_start.setChecked(bool(self.cfg.get("auto_connect_on_start", True)))
        self.chk_auto_on_start.toggled.connect(self.toggle_auto_connect_on_start)

        self.chk_focus_on_click = QCheckBox("点击预览")
        self.chk_focus_on_click.setChecked(bool(self.cfg.get("focus_on_click", True)))
        self.chk_focus_on_click.toggled.connect(self.toggle_focus_on_click)

        self.scan_status = QLabel("")

        # 网格布局：2 列
        conn_grid.addWidget(self.btn_auto_mumu, 0, 0)
        conn_grid.addWidget(btn_manual, 0, 1)
        conn_grid.addWidget(btn_disconnect, 1, 0)
        conn_grid.addWidget(btn_watch, 1, 1)
        conn_grid.addWidget(self.chk_auto_on_start, 2, 0)
        conn_grid.addWidget(self.chk_focus_on_click, 2, 1)
        conn_grid.addWidget(self.scan_status, 3, 0, 1, 2)
        print("[DEBUG] _build_ui: 连接控制创建完成")

        # ADB 设置（紧凑布局）
        print("[DEBUG] _build_ui: 创建 ADB 设置")
        adb_box = QGroupBox("ADB 设置")
        adb_grid = QGridLayout(adb_box)
        adb_grid.setContentsMargins(6, 6, 6, 6)
        adb_grid.setSpacing(4)

        adb_grid.addWidget(QLabel("ADB 路径："), 0, 0)
        default_display = "/adb/adb.exe"
        self.adb_path_edit = QLineEdit(self.cfg.get("adb_path_display", default_display))
        self.adb_path_edit.setMinimumWidth(200)
        adb_grid.addWidget(self.adb_path_edit, 0, 1, 1, 2)

        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self.browse_adb)
        btn_apply = QPushButton("应用并保存")
        btn_apply.clicked.connect(self.apply_adb_path)
        adb_grid.addWidget(btn_browse, 1, 0)
        adb_grid.addWidget(btn_apply, 1, 1)
        print("[DEBUG] _build_ui: ADB 设置创建完成")

        # 组装右侧面板
        print("[DEBUG] _build_ui: 组装右侧面板")
        right_panel_v.addWidget(conn_box)
        right_panel_v.addWidget(adb_box)
        right_panel_v.addStretch(1)

        # 组装主布局：设备列表 + 预览 + 控制面板
        print("[DEBUG] _build_ui: 组装主布局")
        main_h.addWidget(dev_box, 2)  # 设备列表占 2 份
        main_h.addWidget(preview_box, 0)  # 预览框固定宽度，不拉伸
        main_h.addWidget(right_panel, 1)  # 控制面板占 1 份
        print("[DEBUG] _build_ui: 主布局组装完成")

        ov.addLayout(main_h, 1)

        self.nb_content.addTab(overview, "总览")

        # 底部：日志区（使用垂直分割器，顶部为标签区，底部为日志区，可拖动调节）
        self.log_tabs = QTabWidget()
        self.main_log = QPlainTextEdit(); self.main_log.setReadOnly(True)
        self.device_log = QPlainTextEdit(); self.device_log.setReadOnly(True)
        self.log_tabs.addTab(self.main_log, "全局日志")
        self.log_tabs.addTab(self.device_log, "设备日志")

        # 顶部内容 + 底部日志使用垂直分割器，支持高度调节
        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.addWidget(self.nb_content)
        self.right_splitter.addWidget(self.log_tabs)
        self.right_splitter.setStretchFactor(0, 4)
        self.right_splitter.setStretchFactor(1, 3)
        right_v.addWidget(self.right_splitter, 1)

        # 设置初始可视高度（可在配置中通过 qt_nb_content_height/qt_log_height 调整）
        try:
            top_h = int(self.cfg.get("qt_nb_content_height", 800))
            bottom_h = int(self.cfg.get("qt_log_height", 200))
            self.right_splitter.setSizes([max(200, top_h), max(120, bottom_h)])
        except Exception:
            pass

        # 使用滚动容器包裹右侧主区域，当窗口过窄/过矮时出现滚动条而不是强行缩放
        right_scroll = QScrollArea()
        right_scroll.setWidget(right)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 1)

        # 分隔线美化
        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken)
        root_v.addWidget(line)

        # 启动日志
        self.logger.info("Qt UI 已启动。")

    # ---------------- 交互 ----------------
    def browse_adb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 adb.exe", os.getcwd(), "adb.exe (adb.exe)")
        if path:
            self.adb_path_edit.setText(path)

    def apply_adb_path(self) -> None:
        # 支持相对路径：/adb/adb.exe 代表项目根下的 adb/adb.exe
        raw = self.adb_path_edit.text().strip() or "/adb/adb.exe"
        try:
            # 解析为绝对路径
            if os.path.isabs(raw):
                resolved = raw
            else:
                proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
                resolved = os.path.join(proj_root, raw.lstrip("/\\"))
        except Exception:
            resolved = raw
        ok, msg = self.adb.set_adb_path(resolved)
        self.logger.info(msg)
        # 保存配置（显示值与解析值均保存）
        self.cfg = self.config_mgr.load() or {}
        self.cfg["adb_path_display"] = raw
        self.cfg["adb_path"] = self.adb.adb_path
        # 保存窗口几何
        try:
            g = self.geometry()
            self.cfg["qt_geometry"] = {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}
        except Exception:
            pass
        self.config_mgr.save(self.cfg)

    # ---------------- 设备日志 ----------------
    def append_device_log(self, serial: str, line: str) -> None:
        try:
            self.device_log.appendPlainText(f"[{serial}] {line}")
            sb = self.device_log.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception:
            pass

    # ---------------- 设备管理 ----------------
    def refresh_devices(self) -> None:
        try:
            devs = self.adb.list_devices()
        except Exception:
            devs = []
        current = set(self.workers.keys())
        incoming = set(devs)
        # 新增设备
        for s in sorted(incoming - current):
            w = DeviceWorker(serial=s, adb=self.adb, logger=self.logger)
            w.start()
            self.workers[s] = w
            self.logger.info(f"创建工作线程：{s}")
        # 离线设备
        for s in sorted(current - incoming):
            try:
                self.workers[s].stop()
            except Exception:
                pass
            self.workers.pop(s, None)
            self.logger.warn(f"设备离线，停止工作线程：{s}")
            self._close_tab(s)
        # 确保标签
        for s in sorted(incoming):
            self._create_or_update_tab(s)
        # 刷新“总览”页设备列表 + 应用备注标题
        self._refresh_device_list(sorted(incoming))
        self._apply_tab_titles()
        # 根据备注对设备标签排序（总览置于首位）
        try:
            self._sort_device_tabs()
        except Exception:
            pass
        # 更新状态
        for s, tab in list(self.device_tabs.items()):
            tab.refresh_status()

    def _format_device_item_text(self, serial: str) -> str:
        try:
            notes = self.cfg.get("notes", {}) or {}
            note = (notes.get(serial, "") or "").strip()
            # 仅显示端口（127.0.0.1共用地址）
            display = serial
            if ":" in serial and serial.startswith("127.0.0.1:"):
                display = serial.split(":", 1)[1]
            if note:
                return f"{note}  ({display})"
            return display
        except Exception:
            return serial

    def _refresh_device_list(self, devices: list[str]) -> None:
        try:
            if hasattr(self, "device_list") and self.device_list is not None:
                self.device_list.clear()
                # 按备注/端口显示文本排序（优先备注），使用智能排序
                ordered = sorted(list(devices), key=lambda x: self._smart_sort_key(self._format_device_item_text(x) or str(x)))
                for s in ordered:
                    text = self._format_device_item_text(s)
                    item = QListWidgetItem(text)
                    item.setData(Qt.UserRole, s)
                    self.device_list.addItem(item)
        except Exception:
            pass

    def _on_device_item_clicked(self, item) -> None:
        try:
            serial = item.data(Qt.UserRole) or item.text().strip()
            self.logger.info(f"点击设备: {serial}")
            # 点击改为预览（前置模拟器窗口），不再跳转标签
            self._preview_device(str(serial))
        except Exception as e:
            self.logger.error(f"点击设备失败: {e}")
            import traceback
            traceback.print_exc()
    # ---------------- 总览：连接控制 ----------------
    def _preview_device(self, serial: str) -> None:
        """截图并在总览页的预览区显示，不再尝试前置窗口"""
        try:
            if not getattr(self, "preview_label", None):
                self.logger.warning("预览标签不存在")
                return
            self.logger.info(f"开始预览设备: {serial}")
            def _run():
                try:
                    ok, data = self.adb.screencap(serial)
                    self.logger.info(f"截图结果: ok={ok}, data_size={len(data) if data else 0}")
                    if ok and data:
                        # 使用 _post_to_ui 确保在主线程执行
                        def _apply():
                            try:
                                self.logger.info("开始应用预览图像...")
                                img = QImage.fromData(data)
                                self.logger.info(f"QImage 创建: isNull={img.isNull()}, size={img.size()}")
                                if not img.isNull():
                                    pix = QPixmap.fromImage(img)
                                    w = self.preview_label.width() if self.preview_label.width() > 10 else 360
                                    h = self.preview_label.height() if self.preview_label.height() > 10 else 200
                                    scaled_pix = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                    self.logger.info(f"缩放后尺寸: {scaled_pix.size()}")
                                    self.preview_label.setPixmap(scaled_pix)
                                    self.logger.info(f"预览更新成功: {w}x{h}")
                                else:
                                    self.preview_label.setText("无法预览（无效图像）")
                                    self.logger.warning("图像数据无效")
                            except Exception as e:
                                self.logger.error(f"应用预览失败: {e}")
                                import traceback
                                traceback.print_exc()
                        self._post_to_ui(_apply)
                    else:
                        self._post_to_ui(lambda: self.preview_label.setText("无法获取截图"))
                        self.logger.warning("截图失败")
                except Exception as e:
                    self.logger.error(f"预览线程错误: {e}")
                    import traceback
                    traceback.print_exc()
            threading.Thread(target=_run, daemon=True).start()
        except Exception as e:
            self.logger.error(f"预览设备失败: {e}")
            import traceback
            traceback.print_exc()

    def connect_ip_port_dialog(self) -> None:
        ipport, ok = QInputDialog.getText(self, "手动连接 ADB", "端口（本地）或 IP:端口（远程）", text="7555")
        if not ok or not str(ipport).strip():
            return
        ipport = str(ipport).strip()
        # 仅端口时，默认走本地 127.0.0.1:port
        if ":" not in ipport and ipport.isdigit():
            ipport = f"127.0.0.1:{ipport}"
        def _run():
            ok2, out = self.adb.connect(ipport)
            if ok2:
                self.logger.info(out or f"已连接 {ipport}")
                QTimer.singleShot(0, lambda: self._on_one_connected(ipport))
            else:
                self.logger.error(out or f"连接失败 {ipport}")
        threading.Thread(target=_run, daemon=True).start()

    def toggle_auto_connect_on_start(self, checked: bool) -> None:
        try:
            self.cfg["auto_connect_on_start"] = bool(checked)
            self.config_mgr.save(self.cfg)
        except Exception:
            pass

    def _on_one_connected(self, serial: str) -> None:
        # 增量加入：创建工作线程与设备标签，并更新“总览”设备列表
        if serial not in self.workers:
            try:
                w = DeviceWorker(serial=serial, adb=self.adb, logger=self.logger)
                w.start()
                self.workers[serial] = w
                self.logger.info(f"创建工作线程：{serial}")
                self._create_or_update_tab(serial)
            except Exception as e:
                self.logger.error(f"创建设备线程失败 {serial}: {e}")
                return
        # 列表项去重后追加，并显示备注/端口
        try:
            if hasattr(self, "device_list") and self.device_list is not None:
                serials = {self.device_list.item(i).data(Qt.UserRole) for i in range(self.device_list.count())}
                if serial not in serials:
                    text = self._format_device_item_text(serial)
                    item = QListWidgetItem(text)
                    item.setData(Qt.UserRole, serial)
                    self.device_list.addItem(item)
                else:
                    # 刷新文字以体现备注变化
                    for i in range(self.device_list.count()):
                        it = self.device_list.item(i)
                        if it.data(Qt.UserRole) == serial:
                            it.setText(self._format_device_item_text(serial))
                            break
        except Exception:
            pass
        # 若启用“预览窗口”，更新截图预览
        if bool(self.cfg.get("focus_on_click", True)):
            try:
                self._preview_device(serial)
            except Exception:
                pass

    # ---------------- 设备备注 ----------------
    def _display_title_for(self, serial: str) -> str:
        try:
            note = (self.cfg.get("notes", {}) or {}).get(serial, "").strip()
            return note if note else serial
        except Exception:
            return serial

    @staticmethod
    def _smart_sort_key(text: str) -> tuple:
        """
        智能排序键生成函数
        如果首位是数字，则按数字大小排序；否则按字母顺序排序

        示例：
        - "1熊猫" -> (0, 1, "熊猫")  # 首位是数字1
        - "11熊猫" -> (0, 11, "熊猫")  # 首位是数字11
        - "熊猫1" -> (1, "熊猫1")  # 首位不是数字
        """
        text = (text or "").lower().strip()
        if not text:
            return (1, "")

        # 检查首位是否为数字
        i = 0
        while i < len(text) and text[i].isdigit():
            i += 1

        if i > 0:
            # 首位是数字，提取数字部分
            num_str = text[:i]
            rest = text[i:]
            try:
                num = int(num_str)
                return (0, num, rest)  # (0, 数字, 剩余部分)
            except ValueError:
                return (1, text)
        else:
            # 首位不是数字，按字母顺序排序
            return (1, text)

    def _apply_tab_titles(self) -> None:
        try:
            for serial, tab in list(self.device_tabs.items()):
                idx = self.nb_content.indexOf(tab)
                if idx >= 0:
                    self.nb_content.setTabText(idx, self._display_title_for(serial))
        except Exception:
            pass

    def _on_device_item_double_clicked(self, item) -> None:
        try:
            serial = item.data(Qt.UserRole) or item.text().strip()
            serial = str(serial)
            old = (self.cfg.get("notes", {}) or {}).get(serial, "")
            text, ok = QInputDialog.getText(self, "编辑备注", f"为 {serial} 设置备注：", text=old)
            if not ok:
                return
            val = str(text).strip()
            notes = self.cfg.get("notes", {}) or {}
            if val:
                notes[serial] = val
            else:
                if serial in notes:
                    notes.pop(serial, None)
            self.cfg["notes"] = notes
            self.config_mgr.save(self.cfg)
            self._apply_tab_titles()
            try:
                self._sort_device_tabs()
            except Exception:
                pass
            # 刷新列表显示，立即体现备注
            self._refresh_device_list(sorted(self.workers.keys()))
        except Exception:
            pass

    # ---------------- 全局控制：速度/暂停/停止/Toast ----------------
    def on_speed_factor_changed(self, text: str) -> None:
        try:
            val = float(text)
            if val > 0:
                self.speed_factor = val
        except Exception:
            pass

    def get_speed_factor(self) -> float:
        return getattr(self, "speed_factor", 1.0)

    def toggle_pause_all(self, checked: bool) -> None:
        try:
            if checked:
                self.pause_event.set()
                self._toast("已暂停所有任务（试验性，需要任务配合）")
                self.btn_pause_all.setText("继续所有")
            else:
                self.pause_event.clear()
                self._toast("已继续所有任务")
                self.btn_pause_all.setText("暂停所有")
        except Exception:
            pass

    def stop_all_now(self) -> None:
        """停止所有任务并立刻重启程序（无需确认）"""
        try:
            # 禁用停止按钮，防止重复点击
            self.btn_stop_all.setEnabled(False)
            self.btn_stop_all.setText("正在停止...")

            # 显示提示
            self._toast("正在停止所有任务...")
            self.logger.info("[停止所有] 用户触发停止所有任务")

            # 在后台线程中执行停止和重启
            def _stop_and_restart():
                try:
                    # 1. 强制停止所有设备的任务（不等待）
                    for tab in list(self.device_tabs.values()):
                        try:
                            tab.stop_all_tasks_immediately()
                        except Exception:
                            pass

                    # 2. 强制停止所有worker线程（不等待）
                    for serial, worker in list(self.workers.items()):
                        try:
                            worker.stop()
                        except Exception:
                            pass

                    # 3. 快速保存配置（不等待清理）
                    try:
                        self.config_mgr.save(self.cfg)
                    except Exception:
                        pass

                    # 4. 立刻重启程序（不等待）
                    self.logger.info("[停止所有] 立刻重启程序...")
                    from ..common.restart_helper import RestartHelper
                    RestartHelper.restart_and_exit(delay=0.1)

                except Exception as e:
                    self.logger.error(f"[停止所有] 停止失败: {e}")
                    # 如果失败，强制退出
                    try:
                        from ..common.restart_helper import RestartHelper
                        RestartHelper.restart_and_exit(delay=0.1)
                    except Exception:
                        sys.exit(0)

            # 启动后台线程
            stop_thread = threading.Thread(target=_stop_and_restart, daemon=True)
            stop_thread.start()

        except Exception as e:
            self.logger.error(f"[停止所有] 执行失败: {e}")
            try:
                self.btn_stop_all.setEnabled(True)
                self.btn_stop_all.setText("停止所有")
            except Exception:
                pass

    def _toast(self, text: str) -> None:
        # 主窗体的无声提示
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
            dlg = QDialog(self)
            dlg.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            dlg.setAttribute(Qt.WA_TranslucentBackground, True)
            lay = QVBoxLayout(dlg)
            lab = QLabel(text)
            lab.setStyleSheet("QLabel { background: rgba(30,30,30,200); color:#eee; border-radius:6px; padding:10px 14px; }")
            lay.addWidget(lab)
            dlg.adjustSize()
            g = self.geometry(); pos = self.mapToGlobal(g.bottomRight())
            dlg.move(pos.x() - dlg.width() - 20, pos.y() - dlg.height() - 20)
            dlg.show()
            QTimer.singleShot(3000, dlg.close)
        except Exception:
            pass
            self.cfg["notes"] = notes
            self.config_mgr.save(self.cfg)
            self._apply_tab_titles()
            # 刷新列表显示，立即体现备注
            self._refresh_device_list(sorted(self.workers.keys()))
        except Exception:
            pass


    # ---------------- 顶栏：全局模式 ----------------
    def toggle_global_mode(self, checked: bool) -> None:
        try:
            self.cfg["global_mode"] = bool(checked)
            self.config_mgr.save(self.cfg)
            self.logger.info(f"全局操作模式：{'开启' if checked else '关闭'}")
        except Exception:
            pass

    # ---------------- 召唤 MuMu 窗口（尽力尝试） ----------------
    def toggle_focus_on_click(self, checked: bool) -> None:
        try:
            self.cfg["focus_on_click"] = bool(checked)
            self.config_mgr.save(self.cfg)
        except Exception:
            pass

    def _activate_mumu_window(self, serial: str) -> None:
        # 使用 Win32 API 尝试寻找包含“MuMu”字样的窗口并置顶
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            EnumWindows = user32.EnumWindows
            IsWindowVisible = user32.IsWindowVisible
            GetWindowTextW = user32.GetWindowTextW
            SetForegroundWindow = user32.SetForegroundWindow
            GetWindowTextLengthW = user32.GetWindowTextLengthW

            hwnds = []
            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _enum_proc(hwnd, lParam):  # type: ignore[no-redef]
                if IsWindowVisible(hwnd):
                    length = GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value
                        if "MuMu" in title or "模拟器" in title:
                            hwnds.append(hwnd)
                return True
            EnumWindows(_enum_proc, 0)
            if hwnds:
                SetForegroundWindow(hwnds[0])
        except Exception:
            self.logger.info("未能自动激活 MuMu 窗口，可在系统设置中允许前台切换或安装 pywin32 提升可靠性。")


    # ---------------- 置顶 ----------------
    def toggle_always_on_top(self, checked: bool) -> None:
        try:
            # 仅切换置顶标志，避免破坏窗口关闭按钮等其他 flags
            self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(checked))
            self.show()
            # 同步已分离窗口的置顶状态
            try:
                for w in list(self._detached_windows.values()):
                    if w is None:
                        continue
                    flags = w.windowFlags()
                    if bool(checked):
                        w.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
                    else:
                        w.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
                    w.show()
            except Exception:
                pass
            # 保存配置
            self.cfg["always_on_top"] = bool(checked)
            self.config_mgr.save(self.cfg)
        except Exception:
            pass

    # ---------------- 自动连接 MuMu ----------------
    def auto_connect_mumu(self) -> None:
        if getattr(self, "_scan_running", False):
            self.logger.info("自动连接已在进行中，稍候完成后再试。")
            return
        self._scan_running = True
        try:
            self.btn_auto_mumu.setEnabled(False)
            self.scan_status.setText("扫描中...")
        except Exception:
            pass
        self.logger.info("开始并行扫描 MuMu 模拟器端口...")
        threading.Thread(target=self._scan_mumu_ports_parallel, daemon=True).start()

    def _post_to_ui(self, func: Callable[[], None]) -> None:
        try:
            self._ui_invoker.invoked.emit(func)
        except Exception:
            try:
                func()
            except Exception:
                pass
    # ---------------- 掉线监控（完整版） ----------------
    def toggle_offline_watch(self, checked: bool) -> None:
        """启动/停止完整版掉线监控（offline_monitor.py）"""
        from ..ui.tasks.offline_monitor import run_offline_monitor

        try:
            if checked:
                # 检查是否已在运行
                if getattr(self, "_offline_watch_running", False):
                    return

                # 弹出配置对话框
                from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout

                dlg = QDialog(self)
                dlg.setWindowTitle("掉线监控配置")
                dlg.setModal(True)

                layout = QVBoxLayout(dlg)
                layout.addWidget(QLabel("巡检间隔（分钟）："))

                interval_edit = QLineEdit("5")
                interval_edit.setFixedWidth(100)
                layout.addWidget(interval_edit)

                btn_layout = QHBoxLayout()
                btn_ok = QPushButton("确定")
                btn_cancel = QPushButton("取消")
                btn_layout.addWidget(btn_ok)
                btn_layout.addWidget(btn_cancel)
                layout.addLayout(btn_layout)

                btn_ok.clicked.connect(dlg.accept)
                btn_cancel.clicked.connect(dlg.reject)

                if dlg.exec() != QDialog.Accepted:
                    # 用户取消，取消勾选
                    sender = self.sender()
                    if sender and hasattr(sender, "setChecked"):
                        sender.setChecked(False)
                    return

                # 获取配置
                try:
                    interval_minutes = max(1, int(interval_edit.text().strip() or "5"))
                except Exception:
                    interval_minutes = 5

                # 启动监控
                self._offline_watch_running = True
                if not hasattr(self, "_offline_watch_stop"):
                    self._offline_watch_stop = threading.Event()
                else:
                    self._offline_watch_stop.clear()

                def should_stop():
                    return self._offline_watch_stop.is_set()

                def runner():
                    try:
                        run_offline_monitor(
                            app=self,
                            interval_minutes=interval_minutes,
                            should_stop=should_stop,
                            toast=self._toast,
                            log=self.logger.info,
                            threshold=None,
                            verbose=False,
                        )
                    except Exception as e:
                        self.logger.error(f"[OFFMON] 运行异常：{e}")
                    finally:
                        self._offline_watch_running = False
                        # 取消勾选按钮
                        self._post_to_ui(lambda: self._uncheck_offline_watch_button())

                threading.Thread(target=runner, daemon=True).start()
                self._toast(f"已开启完整版掉线监控（间隔 {interval_minutes} 分钟）")
            else:
                # 停止监控
                if hasattr(self, "_offline_watch_stop"):
                    self._offline_watch_stop.set()
                self._offline_watch_running = False
                self._toast("已关闭掉线监控")
        except Exception as e:
            self.logger.error(f"[OFFMON] toggle_offline_watch 异常：{e}")

    def _uncheck_offline_watch_button(self):
        """取消勾选掉线监控按钮"""
        try:
            # 查找掉线监控按钮并取消勾选
            for child in self.findChildren(QPushButton):
                if child.text() == "掉线监控" and child.isCheckable():
                    child.setChecked(False)
                    break
        except Exception:
            pass

    def _scan_mumu_ports_parallel(self) -> None:
        connected_count = 0
        base_port = 16416
        step = 32
        ports = [base_port + step * i for i in range(30)]
        total_ports = len(ports)
        self.logger.info(f"开始并行扫描特定端口 {total_ports} 个（起始16416，步长32，共30个）...")
        try:
            with futures.ThreadPoolExecutor(max_workers=30) as executor:
                future_to_port = {executor.submit(self._try_connect_port, port): port for port in ports}
                for future in futures.as_completed(future_to_port):
                    port = future_to_port[future]
                    try:
                        success = future.result()
                        if success:
                            connected_count += 1
                            # 立即增量创建工作线程和标签页
                            serial = f"127.0.0.1:{port}"
                            self._post_to_ui(lambda s=serial: self._on_one_connected(s))
                    except Exception as e:
                        self.logger.error(f"扫描端口 {port} 时出错: {e}")
        except Exception as e:
            self.logger.error(f"扫描 MuMu 端口失败: {e}")
        finally:
            self._post_to_ui(lambda: self._on_scan_complete(connected_count, total_ports))
    def _try_connect_port(self, port: int) -> bool:
        ipport = f"127.0.0.1:{port}"
        ok, out = self.adb.connect(ipport)
        if ok:
            self.logger.info(f"成功连接: {ipport}")
            return True
        else:
            low = (out or "").lower()
            if "cannot connect" not in low and "failed to connect" not in low:
                self.logger.info(f"连接失败 {ipport}: {out}")
            return False

    def _on_scan_complete(self, connected_count: int, total_ports: int) -> None:
        try:
            self._scan_running = False
            self.logger.info(f"并行扫描完成，成功连接 {connected_count}/{total_ports} 个 MuMu 设备")
            self.btn_auto_mumu.setEnabled(True)
            self.scan_status.setText("")
            self.refresh_devices()
            # 自动连接完成后，按备注对标签自动排序
            try:
                self._sort_device_tabs()
            except Exception:
                pass
        except Exception:
            pass
    def disconnect_selected_device(self) -> None:
        try:
            item = self.device_list.currentItem()
            if not item:
                self._toast("请先在设备列表中选择一个设备")
                return
            serial = item.data(Qt.UserRole) or item.text().strip()
            serial = str(serial)
            ok, out = self.adb.disconnect(serial)
            if ok:
                self.logger.info(f"已断开: {serial}")
            else:
                self.logger.error(f"断开失败 {serial}: {out}")
            QTimer.singleShot(100, self.refresh_devices)
        except Exception as e:
            self.logger.error(f"断开设备异常: {e}")

    def _create_or_update_tab(self, serial: str) -> None:
        if serial in self.device_tabs:
            return
        tab = DeviceTabQt(self, serial)
        self.nb_content.addTab(tab, self._display_title_for(serial))
        self.device_tabs[serial] = tab

    def _close_tab(self, serial: str) -> None:
        tab = self.device_tabs.get(serial)
        if not tab:
            return

        # 检查 tab 是否还有效
        try:
            _ = tab.isVisible()
        except RuntimeError:
            # tab 已被 Qt 删除，仅清理字典
            print(f"[DEBUG] _close_tab: tab 已删除，仅清理字典: {serial}")
            self.device_tabs.pop(serial, None)
            return

        try:
            idx = self.nb_content.indexOf(tab)
            if idx >= 0:
                self.nb_content.removeTab(idx)
        except RuntimeError:
            print(f"[DEBUG] _close_tab: indexOf 失败: {serial}")

        try:
            tab.deleteLater()
        except Exception:
            pass
        self.device_tabs.pop(serial, None)

    # ---------------- 标签排序/分离 ----------------
    def _sort_device_tabs(self) -> None:
        """将设备标签根据备注（标题）排序；保留“总览”在首位。"""
        try:
            count = self.nb_content.count()
            if count <= 2:
                return
            # 生成排序目标（标题、serial、tab）
            items = []
            for serial, tab in list(self.device_tabs.items()):
                # 检查 tab 是否还有效
                try:
                    _ = tab.isVisible()
                    title = self._display_title_for(serial)
                    items.append((title or "", serial, tab))
                except RuntimeError:
                    # tab 已被 Qt 删除，跳过
                    print(f"[DEBUG] 排序跳过已删除的 tab: {serial}")
                    continue
            # 使用智能排序（首位数字按数字大小，否则按字母顺序）
            items.sort(key=lambda t: self._smart_sort_key(t[0]))
            # 逐个移动到目标位置（从索引1开始）
            bar = self.nb_content.tabBar()
            target = 1
            for _, serial, tab in items:
                try:
                    cur = self.nb_content.indexOf(tab)
                    print(f"[DEBUG] 排序: {serial} 当前索引={cur}, 目标索引={target}")
                    if cur >= 0 and cur != target:
                        try:
                            bar.moveTab(cur, target)
                            print(f"[DEBUG] moveTab 成功: {cur} -> {target}")
                        except Exception as e:
                            # 兼容：移除再插入
                            print(f"[DEBUG] moveTab 失败，使用 removeTab/insertTab: {e}")
                            text = self._display_title_for(serial)
                            self.nb_content.removeTab(cur)
                            self.nb_content.insertTab(min(target, self.nb_content.count()), tab, text)
                            tab.setVisible(True)
                            tab.show()  # 确保显示
                    target += 1
                except RuntimeError:
                    print(f"[DEBUG] 排序时 tab 已删除: {serial}")
                    continue
        except Exception as e:
            print(f"[DEBUG] _sort_device_tabs 异常: {e}")
            import traceback
            traceback.print_exc()

    def adjust_current_tab_spacing(self, delta: int) -> None:
        """调整当前设备页签内横向间隙（每+/-2像素）。"""
        try:
            w = self.nb_content.currentWidget()
            from .device_tab_qt import DeviceTabQt
            if isinstance(w, DeviceTabQt):
                w.adjust_horizontal_spacing(delta)
        except Exception:
            pass

    def _on_tab_bar_double_clicked(self, index: int) -> None:
        """双击设备标签分离为独立窗口；双击“总览”忽略。"""
        try:
            if index <= 0:
                return
            tab = self.nb_content.widget(index)
            if not tab:
                return
            # 找到对应的 serial
            serial = None
            for s, t in list(self.device_tabs.items()):
                if t is tab:
                    serial = s
                    break
            if not serial:
                return
            self._detach_tab(serial)
        except Exception:
            pass

    def _detach_tab(self, serial: str) -> None:
        try:
            # 若已分离，直接唤起现有窗口
            wnd_existing = self._detached_windows.get(serial)
            if wnd_existing is not None:
                try:
                    wnd_existing.show(); wnd_existing.raise_(); wnd_existing.activateWindow()
                    return
                except Exception:
                    pass
            tab = self.device_tabs.get(serial)
            if not tab:
                return

            idx = self.nb_content.indexOf(tab)
            if idx >= 0:
                # 关键修复：QTabWidget.removeTab() 会删除 widget
                # 必须先 setParent(None) 转移所有权，然后再 removeTab
                # 但要确保 device_tabs 字典保持对 tab 的引用
                print(f"[DEBUG] 准备分离: {serial}, 索引={idx}, tab_id={id(tab)}")
                # 先从标签栏移除（这不会删除 widget，因为我们持有引用）
                self.nb_content.removeTab(idx)
                # tab 仍在 device_tabs[serial] 中，不会被垃圾回收
                print(f"[DEBUG] 从标签栏移除: {serial}")

            # 创建独立窗口并承载该标签内容（顶层窗口，无父级）
            # 使用内部类以正确覆盖 closeEvent
            parent_self = self
            class DetachedWindow(QMainWindow):
                def __init__(self, device_serial: str):
                    super().__init__(None)
                    self._serial = device_serial

                def closeEvent(self, event):
                    try:
                        parent_self._reattach_tab(self._serial)
                    except Exception as e:
                        print(f"回贴标签失败 {self._serial}: {e}")
                    finally:
                        event.accept()

            wnd = DetachedWindow(serial)
            wnd.setWindowTitle(self._display_title_for(serial))
            # 继承主窗体置顶状态
            try:
                if bool(self.cfg.get("always_on_top", False)):
                    wnd.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            except Exception:
                pass
            try:
                tab.show()
            except Exception:
                pass
            wnd.setCentralWidget(tab)
            try:
                s = tab.sizeHint()
                w = max(640, int(getattr(s, "width", lambda: 640)()))
                h = max(480, int(getattr(s, "height", lambda: 480)()))
                wnd.resize(w, h)
            except Exception:
                try:
                    wnd.resize(800, 600)
                except Exception:
                    pass
            try:
                wnd.setAttribute(Qt.WA_DeleteOnClose, False)  # 手动控制删除
            except Exception:
                pass
            self._detached_windows[serial] = wnd
            # destroyed 信号作为兜底
            try:
                wnd.destroyed.connect(lambda *_: self._reattach_tab(serial))
            except Exception:
                pass
            wnd.show(); wnd.raise_(); wnd.activateWindow()
        except Exception as e:
            print(f"分离标签失败 {serial}: {e}")

    def _reattach_tab(self, serial: str) -> None:
        try:
            # 防止重复回贴
            if serial not in self._detached_windows:
                print(f"[DEBUG] 回贴跳过（不在分离列表）: {serial}")
                return

            wnd = self._detached_windows.pop(serial, None)
            if wnd is None:
                print(f"[DEBUG] 分离窗口不存在: {serial}")
                return

            # 关键修复：先从 device_tabs 获取 tab（这是唯一可靠的引用）
            tab = self.device_tabs.get(serial)
            if tab is None:
                print(f"[DEBUG] device_tabs 中无 tab: {serial}")
                try:
                    wnd.close()
                    wnd.deleteLater()
                except Exception:
                    pass
                return

            # 检查 tab 对象是否还有效
            try:
                _ = tab.isVisible()
            except RuntimeError:
                print(f"[DEBUG] tab 对象已被 Qt 删除: {serial}")
                try:
                    wnd.close()
                    wnd.deleteLater()
                except Exception:
                    pass
                return

            print(f"[DEBUG] 准备回贴 tab: {serial}, tab_id={id(tab)}")

            # 检查是否已在主标签栏中
            try:
                existing_idx = self.nb_content.indexOf(tab)
                if existing_idx >= 0:
                    print(f"[DEBUG] tab 已在标签栏索引 {existing_idx}，仅关闭窗口")
                    try:
                        wnd.close()
                        wnd.deleteLater()
                    except Exception:
                        pass
                    return
            except RuntimeError:
                print(f"[DEBUG] indexOf 失败: {serial}")
                return

            # 先从窗口中移除 centralWidget（但不删除）
            try:
                current_central = wnd.centralWidget()
                if current_central is tab:
                    wnd.setCentralWidget(None)
                    print(f"[DEBUG] 已从窗口移除 centralWidget")
            except Exception as e:
                print(f"[DEBUG] 移除 centralWidget 失败: {e}")

            # 重新添加回主标签
            title = self._display_title_for(serial)
            print(f"[DEBUG] 准备添加标签: serial={serial}, title={title}, tab_id={id(tab)}")

            # 确保 tab 可见且启用
            try:
                tab.setVisible(True)
                tab.setEnabled(True)
                tab.show()
                print(f"[DEBUG] tab 设置为可见")
            except Exception as e:
                print(f"[DEBUG] 设置 tab 可见失败: {e}")

            new_idx = self.nb_content.addTab(tab, title)
            print(f"[DEBUG] addTab 返回索引: {new_idx}, 当前标签总数: {self.nb_content.count()}")

            # 关闭分离窗口
            try:
                wnd.close()
                wnd.deleteLater()
                print(f"[DEBUG] 分离窗口已关闭")
            except Exception as e:
                print(f"[DEBUG] 关闭窗口失败: {e}")

            # 按备注重新排序
            print(f"[DEBUG] 开始排序前，标签总数: {self.nb_content.count()}")
            try:
                self._sort_device_tabs()
                print(f"[DEBUG] 排序后，标签总数: {self.nb_content.count()}")
            except Exception as e:
                print(f"[DEBUG] 排序失败: {e}")

            # 最终验证并自动切换到该标签
            final_idx = self.nb_content.indexOf(tab)

            # 列出所有当前标签
            print(f"[DEBUG] 当前所有标签:")
            for i in range(self.nb_content.count()):
                tab_text = self.nb_content.tabText(i)
                tab_widget = self.nb_content.widget(i)
                is_visible = tab_widget.isVisible() if tab_widget else False
                print(f"  [{i}] '{tab_text}' (visible={is_visible}, widget={tab_widget is not None})")

            if final_idx >= 0:
                try:
                    # 关键修复：QTabWidget 的行为是只有当前标签页可见，其他隐藏
                    # 这是正常的 Qt 行为，不需要强制所有标签页都可见
                    # 只需要确保当前标签页可见即可

                    # 使用 QTimer 延迟切换，确保 Qt 事件循环处理完毕
                    from PySide6.QtCore import QTimer

                    def do_switch():
                        try:
                            # 切换到目标标签
                            self.nb_content.setCurrentIndex(final_idx)

                            # 确保当前标签页可见
                            current_widget = self.nb_content.currentWidget()
                            if current_widget:
                                current_widget.setVisible(True)
                                current_widget.show()

                            # 强制刷新
                            self.nb_content.update()
                            print(f"✓ 标签已回贴并切换: {serial} (索引: {final_idx})")
                        except Exception as e:
                            print(f"✓ 标签已回贴: {serial} (索引: {final_idx}，切换失败: {e})")

                    # 使用 QTimer 延迟 100ms 执行，让 Qt 事件循环处理完毕
                    QTimer.singleShot(100, do_switch)
                except Exception as e:
                    print(f"✓ 标签已回贴: {serial} (索引: {final_idx}，切换失败: {e})")
            else:
                print(f"⚠ 标签回贴后未找到: {serial}")
        except Exception as e:
            print(f"回贴标签异常 {serial}: {e}")
            import traceback
            traceback.print_exc()

    # ---------------- 移动界面 ----------------
    def open_mobile_view(self) -> None:
        """打开移动端界面并关闭主界面"""
        try:
            # 如果已经打开，则激活窗口
            if self.mobile_window is not None:
                try:
                    self.mobile_window.show()
                    self.mobile_window.raise_()
                    self.mobile_window.activateWindow()
                    return
                except Exception:
                    self.mobile_window = None

            # 导入移动界面（重构版，等比缩放+拖拽）
            from .mobile_view_qt_new import MobileMainWindow

            # 创建移动界面窗口
            self.mobile_window = MobileMainWindow(self)

            # 设置关闭事件处理
            def on_mobile_closed():
                """移动界面关闭时重新显示主界面"""
                self.mobile_window = None
                self.show()
                self.raise_()
                self.activateWindow()
                self.logger.info("移动端界面已关闭，恢复主界面")

            # 重写移动窗口的closeEvent
            original_close = self.mobile_window.closeEvent
            def new_close_event(event):
                original_close(event)
                on_mobile_closed()
            self.mobile_window.closeEvent = new_close_event

            # 显示移动界面
            self.mobile_window.show()

            # 隐藏主界面
            self.hide()

            self.logger.info("已切换到移动端界面")
        except Exception as e:
            self.logger.error(f"打开移动界面失败: {e}")
            import traceback
            traceback.print_exc()

    # ---------------- 日志 ----------------
    def _append_main_log(self, line: str) -> None:
        self.main_log.appendPlainText(line)
        self.main_log.verticalScrollBar().setValue(self.main_log.verticalScrollBar().maximum())

    # ---------------- 关闭 ----------------
    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            # 停止所有设备工作线程
            for w in list(self.workers.values()):
                try:
                    w.stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # 保存分割器高度与窗口几何
            if hasattr(self, 'right_splitter'):
                sizes = self.right_splitter.sizes()
                if sizes and len(sizes) >= 2:
                    self.cfg["qt_nb_content_height"] = sizes[0]
                    self.cfg["qt_log_height"] = sizes[1]
            geom = self.geometry()
            self.cfg["qt_geometry"] = {"x": geom.x(), "y": geom.y(), "w": geom.width(), "h": geom.height()}
            self.config_mgr.save(self.cfg)
        except Exception:
            pass
        try:
            self.apply_adb_path()
        except Exception:
            pass
        super().closeEvent(event)


def launch() -> None:
    app = QApplication(sys.argv or ["app"])
    w = AppQt()
    w.show()
    sys.exit(app.exec())
