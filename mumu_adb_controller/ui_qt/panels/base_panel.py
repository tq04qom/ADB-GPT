"""
扩展面板基类
"""
from __future__ import annotations
from typing import Callable, TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QPushButton

if TYPE_CHECKING:
    from ..device_tab_qt import DeviceTabQt


class BasePanel(QWidget):
    """扩展面板基类，提供公共方法"""

    def __init__(self, tab: "DeviceTabQt"):
        super().__init__(parent=tab)
        self.tab = tab
        self.app = tab.app
        self.serial = tab.serial

    def _toast(self, text: str):
        """非阻塞提示（通过信号到主线程）"""
        try:
            self.tab._toast(text)
        except Exception:
            pass

    def _log(self, msg: str):
        """设备日志"""
        self.tab.device_log(msg)

    def _start_with_button(
        self,
        task_id: str,
        button: QPushButton,
        runner: Callable[[Callable[[], bool]], None]
    ):
        """启动任务并管理按钮状态"""
        self.tab._start_task_with_button(task_id, button, runner)

