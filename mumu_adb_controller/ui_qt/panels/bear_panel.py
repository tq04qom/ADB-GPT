"""
打熊面板
"""
from __future__ import annotations
import datetime as _dt
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QVBoxLayout, QLabel, QPushButton, QGroupBox,
    QGridLayout, QCheckBox, QLineEdit, QComboBox
)

from .base_panel import BasePanel
from ...ui.tasks.bear_mode import run_bear_mode, BearOptions

if TYPE_CHECKING:
    from ..device_tab_qt import DeviceTabQt


class BearPanel(BasePanel):
    """打熊模式面板"""

    def __init__(self, tab: "DeviceTabQt"):
        super().__init__(tab)
        try:
            setattr(self.tab, "box_bear", self)
        except Exception:
            pass
        box = QGroupBox("打熊模式")
        root = QVBoxLayout(self)
        root.addWidget(box)
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel("打熊时间(HHMMSS)"), 0, 0)
        self.ed_time = QLineEdit("203000")
        self.ed_time.setFixedWidth(80)
        grid.addWidget(self.ed_time, 0, 1)
        grid.addWidget(QLabel("执行日"), 0, 2)
        self.day_map = {"单双日皆打": "both", "仅单日": "odd", "仅双日": "even"}
        self.cb_day = QComboBox()
        self.cb_day.addItems(list(self.day_map.keys()))
        grid.addWidget(self.cb_day, 0, 3)

        self.ck_send = QCheckBox("主动发车")
        self.ck_send.setChecked(True)
        grid.addWidget(self.ck_send, 1, 0, 1, 2)
        grid.addWidget(QLabel("车头模式"), 1, 2)
        self.head_map = {"固定车头": "fixed", "随机上车": "random"}
        self.cb_head = QComboBox()
        self.cb_head.addItems(list(self.head_map.keys()))
        grid.addWidget(self.cb_head, 1, 3)

        grid.addWidget(QLabel("发车间隔(秒)"), 2, 0)
        self.ed_interval = QLineEdit("300")
        self.ed_interval.setFixedWidth(80)
        grid.addWidget(self.ed_interval, 2, 1)
        grid.addWidget(QLabel("延迟发车(秒)"), 2, 2)
        self.ed_delay = QLineEdit("0")
        self.ed_delay.setFixedWidth(80)
        grid.addWidget(self.ed_delay, 2, 3)

        self.btn = QPushButton("启动打熊模式")
        grid.addWidget(self.btn, 3, 0, 1, 4)
        self.btn._qt_start_handler = self._on_start
        self.btn.clicked.connect(self._on_start)

        self._load_defaults()

    def _load_defaults(self):
        try:
            cfg = getattr(self.app, "cfg", {}) or {}
            opts = (cfg.get("bear_options", {}) or {}).get(self.serial)
            if not opts:
                return
            time_val = str(opts.get("time", "")).strip()
            if time_val:
                if time_val.isdigit() and len(time_val) < 6:
                    time_val = time_val.zfill(6)
                self.ed_time.setText(time_val)
            day_label = opts.get("day_mode_label")
            day_code = opts.get("day_mode")
            if day_label in self.day_map:
                self.cb_day.setCurrentText(day_label)
            elif day_code:
                for k, v in self.day_map.items():
                    if v == day_code:
                        self.cb_day.setCurrentText(k)
                        break
            self.ck_send.setChecked(bool(opts.get("send_car", True)))
            head_label = opts.get("head_mode_label")
            head_code = opts.get("head_mode")
            if head_label in self.head_map:
                self.cb_head.setCurrentText(head_label)
            elif head_code:
                for k, v in self.head_map.items():
                    if v == head_code:
                        self.cb_head.setCurrentText(k)
                        break
            iv = str(opts.get("interval", "")).strip()
            if iv:
                self.ed_interval.setText(iv)
            delay = str(opts.get("delay", "")).strip()
            if delay:
                self.ed_delay.setText(delay)
        except Exception:
            pass

    def _save_defaults(self, options: BearOptions, time_raw: str):
        try:
            cfg = getattr(self.app, "cfg", {}) or {}
            cfg.setdefault("bear_options", {})
            cfg["bear_options"][self.serial] = {
                "time": time_raw,
                "day_mode_label": self.cb_day.currentText(),
                "day_mode": options.day_mode,
                "send_car": bool(self.ck_send.isChecked()),
                "head_mode_label": self.cb_head.currentText(),
                "head_mode": options.head_mode,
                "interval": str(options.interval_sec),
                "delay": str(options.delay_sec),
            }
            self.app.config_mgr.save(cfg)
        except Exception:
            pass

    def _on_start(self):
        raw = (self.ed_time.text() or "").strip()
        if len(raw) != 6 or not raw.isdigit():
            self._toast("打熊时间需为六位数字（HHMMSS），例如 203000")
            return
        hh, mm, ss = int(raw[:2]), int(raw[2:4]), int(raw[4:])
        if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
            self._toast("打熊时间超出有效范围")
            return
        options = BearOptions(
            target_time=_dt.time(hour=hh, minute=mm, second=ss),
            day_mode=self.day_map.get(self.cb_day.currentText(), "both"),
            send_car=bool(self.ck_send.isChecked()),
            head_mode=self.head_map.get(self.cb_head.currentText(), "random"),
            interval_sec=max(1, int((self.ed_interval.text() or "300").strip() or 300)),
            delay_sec=max(0, int((self.ed_delay.text() or "0").strip() or 0)),
        )
        self._save_defaults(options, raw)

        def runner(should_stop):
            run_bear_mode(
                self.app, self.serial, toast=self._toast, log=self._log,
                should_stop=should_stop, options=options,
                threshold=None, verbose=False,
            )

        if bool(self.app.cfg.get("global_mode", False)):
            for t in list(self.app.device_tabs.values()):
                box = getattr(t, "box_bear", None)
                if box and hasattr(box, "btn"):
                    def make_runner(tt: "DeviceTabQt"):
                        def r(should_stop):
                            run_bear_mode(
                                self.app, tt.serial,
                                toast=tt._toast,
                                log=lambda m: tt._sig.device_log.emit(m),
                                should_stop=should_stop, options=options,
                                threshold=None, verbose=False,
                            )
                        return r
                    t._start_task_with_button("bear_mode", box.btn, make_runner(t))
        else:
            self._start_with_button("bear_mode", self.btn, runner)

