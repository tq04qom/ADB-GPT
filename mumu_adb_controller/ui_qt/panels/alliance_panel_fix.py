"""
联盟功能面板（修复版，无空字节）
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox
)

from .base_panel import BasePanel
from ...ui.tasks.auto_like import run_auto_like
from ...ui.tasks.fast_join_rally import run_fast_join_rally
from ...ui.tasks.promote_rank4 import run_promote_rank4
from ...ui.tasks.auto_garrison import run_close_alliance_help, run_open_alliance_help
from ...ui.tasks.build_flag import run_build_flag

if TYPE_CHECKING:
    from ..device_tab_qt import DeviceTabQt


class AlliancePanel(BasePanel):
    """联盟功能面板（支持全局操作模式）"""

    def __init__(self, tab: "DeviceTabQt"):
        super().__init__(tab)
        try:
            setattr(self.tab, "box_alliance", self)
        except Exception:
            pass
        box = QGroupBox("联盟功能")
        root = QVBoxLayout(self)
        root.addWidget(box)
        # 两排布局：第一排 关闭/打开上车；第二排 点赞/秒进/四阶
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        box.setLayout(v)
        row1 = QHBoxLayout(); row1.setContentsMargins(0, 0, 0, 0); row1.setSpacing(8)
        row2 = QHBoxLayout(); row2.setContentsMargins(0, 0, 0, 0); row2.setSpacing(8)
        btn_close = QPushButton("关闭上车")
        btn_open = QPushButton("打开上车")
        self.btn_like = QPushButton("自动点赞")
        self.btn_fast = QPushButton("秒进集结")
        self.btn_rank4 = QPushButton("一键四阶")
        self.btn_build_flag = QPushButton("建旗子")
        for b in (btn_close, btn_open):
            row1.addWidget(b)
        for b in (self.btn_like, self.btn_fast, self.btn_rank4, self.btn_build_flag):
            row2.addWidget(b)
        v.addLayout(row1)
        v.addLayout(row2)
        btn_close.clicked.connect(self._on_close_help)
        # 绑定为修复版方法
        btn_open.clicked.connect(self._on_open_help)
        self.btn_like._qt_start_handler = self._on_like
        self.btn_like.clicked.connect(self._on_like)
        self.btn_fast._qt_start_handler = self._on_fast_join
        self.btn_fast.clicked.connect(self._on_fast_join)
        self.btn_rank4._qt_start_handler = self._on_rank4
        self.btn_rank4.clicked.connect(self._on_rank4)
        self.btn_build_flag._qt_start_handler = self._on_build_flag
        self.btn_build_flag.clicked.connect(self._on_build_flag)

    # ---- 联盟帮助：关闭/打开（支持全局） ----
    def _on_close_help(self):
        def make_task(tab: "DeviceTabQt"):
            def task():
                run_close_alliance_help(
                    self.app, tab.serial,
                    toast=tab._toast,
                    log=lambda m: tab._sig.device_log.emit(m),
                    threshold=None, verbose=False
                )
            return task
        if bool(self.app.cfg.get("global_mode", False)):
            for t in list(self.app.device_tabs.values()):
                if t.serial in self.app.workers:
                    self.app.workers[t.serial].submit(make_task(t))
        else:
            if self.serial in self.app.workers:
                self.app.workers[self.serial].submit(make_task(self.tab))

    def _on_open_help(self):
        def make_task(tab: "DeviceTabQt"):
            def task():
                run_open_alliance_help(
                    self.app, tab.serial,
                    toast=tab._toast,
                    log=lambda m: tab._sig.device_log.emit(m),
                    threshold=None, verbose=False
                )
            return task
        if bool(self.app.cfg.get("global_mode", False)):
            for t in list(self.app.device_tabs.values()):
                if t.serial in self.app.workers:
                    self.app.workers[t.serial].submit(make_task(t))
        else:
            if self.serial in self.app.workers:
                self.app.workers[self.serial].submit(make_task(self.tab))

    # ---- 自动点赞（支持全局） ----
    def _on_like(self):
        def make_runner(tab: "DeviceTabQt"):
            def runner(should_stop):
                run_auto_like(
                    self.app, tab.serial,
                    toast=tab._toast,
                    log=lambda m: tab._sig.device_log.emit(m),
                    should_stop=should_stop,
                    threshold=None, verbose=False
                )
            return runner
        if bool(self.app.cfg.get("global_mode", False)):
            for t in list(self.app.device_tabs.values()):
                box = getattr(t, "box_alliance", None)
                if box and hasattr(box, "btn_like"):
                    t._start_task_with_button("auto_like", box.btn_like, make_runner(t))
        else:
            self._start_with_button("auto_like", self.btn_like, make_runner(self.tab))

    # ---- 秒进集结（支持全局） ----
    def _on_fast_join(self):
        def make_runner(tab: "DeviceTabQt"):
            def runner(should_stop):
                run_fast_join_rally(
                    self.app, tab.serial,
                    toast=tab._toast,
                    log=lambda m: tab._sig.device_log.emit(m),
                    should_stop=should_stop,
                    threshold=None, verbose=False
                )
            return runner
        if bool(self.app.cfg.get("global_mode", False)):
            for t in list(self.app.device_tabs.values()):
                box = getattr(t, "box_alliance", None)
                if box and hasattr(box, "btn_fast"):
                    t._start_task_with_button("fast_join", box.btn_fast, make_runner(t))
        else:
            self._start_with_button("fast_join", self.btn_fast, make_runner(self.tab))

    # ---- 一键四阶（按你的要求：仅当前设备） ----
    def _on_rank4(self):
        def runner(should_stop):
            run_promote_rank4(
                self.app, self.serial,
                toast=self._toast, log=self._log,
                should_stop=should_stop,
                threshold=None, verbose=False
            )
        self._start_with_button("promote_rank4", self.btn_rank4, runner)

    # ---- 建旗子（支持当前设备） ----
    def _on_build_flag(self):
        def runner(should_stop):
            run_build_flag(
                self.app, self.serial,
                toast=self._toast, log=self._log,
                should_stop=should_stop,
                threshold=None, verbose=False
            )
        # 建旗子默认仅在当前设备运行（因为行为比较设备专用）
        self._start_with_button("build_flag", self.btn_build_flag, runner)

