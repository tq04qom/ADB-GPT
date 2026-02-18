"""
小工具面板
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox
)

from .base_panel import BasePanel
from ...ui.tasks.init_to_wild import run_init_to_wild
from ...ui.tasks.withdraw_troops import run_withdraw_troops
from ...ui.helpers.tool_launcher import launch_ui_cropper

if TYPE_CHECKING:
    from ..device_tab_qt import DeviceTabQt


class ToolsPanel(BasePanel):
    """小工具面板"""

    def __init__(self, tab: "DeviceTabQt"):
        super().__init__(tab)
        try:
            setattr(self.tab, "box_tools", self)
        except Exception:
            pass
        box = QGroupBox("小工具")
        root = QVBoxLayout(self)
        root.addWidget(box)
        hl = QHBoxLayout()
        box.setLayout(hl)

        # 截图工具
        self.btn_shot = QPushButton("截图工具")
        hl.addWidget(self.btn_shot)
        self.btn_shot.clicked.connect(self._on_shot)

        # 初始化到野外
        self.btn_init = QPushButton("初始化到野外")
        hl.addWidget(self.btn_init)
        self.btn_init.clicked.connect(self._on_init)

        # 一键撤军
        self.btn_withdraw = QPushButton("一键撤军")
        hl.addWidget(self.btn_withdraw)
        self.btn_withdraw._qt_start_handler = self._on_withdraw
        self.btn_withdraw.clicked.connect(self._on_withdraw)

    def _on_shot(self):
        try:
            launch_ui_cropper(self._toast, self._log)
        except Exception as e:
            self._toast("截图工具启动失败")

    def _on_init(self):
        """初始化到野外（支持全局操作模式）"""
        def task():
            run_init_to_wild(
                self.app, self.serial,
                toast=self._toast, log=self._log,
                threshold=None, verbose=False
            )

        # 当前设备执行
        if self.serial in self.app.workers:
            self.app.workers[self.serial].submit(task)

        # 全局模式：其他设备也执行
        if bool(self.app.cfg.get("global_mode", False)):
            for tab in list(self.app.device_tabs.values()):
                if tab is self.tab or tab.serial not in self.app.workers:
                    continue
                def make_task(t):
                    def t_task():
                        run_init_to_wild(
                            self.app, t.serial,
                            toast=t._toast,
                            log=lambda m: t._sig.device_log.emit(m),
                            threshold=None, verbose=False
                        )
                    return t_task
                self.app.workers[tab.serial].submit(make_task(tab))

    def _on_withdraw(self):
        """一键撤军（支持全局操作模式）"""
        def runner(should_stop):
            run_withdraw_troops(
                self.app, self.serial,
                toast=self._toast, log=self._log,
                should_stop=should_stop,
                threshold=None, verbose=False
            )

        # 当前设备执行（带按钮控制）
        self._start_with_button("withdraw", self.btn_withdraw, runner)

        # 全局模式：其他设备也执行（无按钮绑定）
        if bool(self.app.cfg.get("global_mode", False)):
            for tab in list(self.app.device_tabs.values()):
                if tab is self.tab or tab.serial not in self.app.workers:
                    continue
                def make_runner(t):
                    def r(should_stop):
                        run_withdraw_troops(
                            self.app, t.serial,
                            toast=t._toast,
                            log=lambda m: t._sig.device_log.emit(m),
                            should_stop=should_stop,
                            threshold=None, verbose=False
                        )
                    return r
                # 直接提交到工作线程，不绑定按钮
                stop_ev = getattr(self, f"_withdraw_global_{tab.serial}_stop", None)
                if stop_ev is None:
                    import threading
                    stop_ev = threading.Event()
                    setattr(self, f"_withdraw_global_{tab.serial}_stop", stop_ev)
                else:
                    stop_ev.clear()

                def should_stop_fn(ev=stop_ev):
                    return ev.is_set()

                self.app.workers[tab.serial].submit(lambda r=make_runner(tab): r(should_stop_fn))

