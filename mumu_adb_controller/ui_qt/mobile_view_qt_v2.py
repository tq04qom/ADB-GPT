"""
移动端界面 - 完整功能版本
直接复用主界面的DeviceTabQt，只调整窗口布局为移动端风格
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget
)

from ..common.logger import Logger
from ..core.adb import AdbClient
from ..common.worker import DeviceWorker

# 直接导入主界面的设备标签页
from .device_tab_qt import DeviceTabQt


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
        
        # 设备标签页
        self.device_tabs = QTabWidget()
        self.device_tabs.setTabPosition(QTabWidget.North)
        
        # 设置标签页字体
        tab_font = QFont()
        tab_font.setPointSize(13)
        self.device_tabs.setFont(tab_font)
        
        # 设置标签页样式
        self.device_tabs.setStyleSheet("""
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
        overview_tab = self._create_overview_tab()
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
            label_font.setPointSize(15)
            label.setFont(label_font)
            label.setAlignment(Qt.AlignCenter)
            placeholder_layout.addWidget(label)
            
            self.device_tabs.addTab(placeholder, "无设备")
        else:
            # 为每个设备创建标签页（直接使用DeviceTabQt）
            for serial in serials:
                device_tab = DeviceTabQt(self.app, serial)
                # 使用备注名称或端口号
                tab_name = self._get_device_display_name(serial)
                self.device_tabs.addTab(device_tab, f"📱 {tab_name}")
    
    def _create_overview_tab(self) -> QWidget:
        """创建初始页"""
        from .panels.tools_panel import ToolsPanel
        
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(15)
        
        # 欢迎标题
        welcome_label = QLabel("🏠 欢迎使用移动端界面")
        welcome_font = QFont()
        welcome_font.setPointSize(16)
        welcome_font.setBold(True)
        welcome_label.setFont(welcome_font)
        welcome_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(welcome_label)
        
        # 说明文字
        info_label = QLabel(
            "移动端界面提供与主界面完全一致的功能\n"
            "所有参数和设置都已同步\n\n"
            "请选择设备标签页开始使用"
        )
        info_font = QFont()
        info_font.setPointSize(13)
        info_label.setFont(info_font)
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 全局工具面板
        try:
            tools_panel = ToolsPanel(self.app, None)
            layout.addWidget(tools_panel)
        except Exception:
            pass
        
        layout.addStretch()
        
        return tab

