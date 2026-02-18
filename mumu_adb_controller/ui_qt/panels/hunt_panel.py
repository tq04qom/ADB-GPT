"""
打野面板
"""
from __future__ import annotations
from typing import List, TYPE_CHECKING

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QGridLayout, QRadioButton, QCheckBox, QLineEdit, QWidget
)

from .base_panel import BasePanel
from ...ui.tasks.sweep_hunt import run_sweep_hunt

if TYPE_CHECKING:
    from ..device_tab_qt import DeviceTabQt


class HuntPanel(BasePanel):
    """打野面板"""

    def __init__(self, tab: "DeviceTabQt"):
        super().__init__(tab)
        # 注册到所属标签，便于全局分发时访问对应按钮
        try:
            setattr(self.tab, "box_hunt", self)
        except Exception:
            pass
        box = QGroupBox("打野参数")
        root = QVBoxLayout(self)
        root.addWidget(box)
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)

        # 类型
        grid.addWidget(QLabel("打野类型"), 0, 0)
        self.rb_beast = QRadioButton("野兽")
        self.rb_beast.setChecked(True)
        self.rb_beast.toggled.connect(self._update_hunt_type)
        self.rb_monster = QRadioButton("巨兽")
        self.rb_monster.toggled.connect(self._update_hunt_type)
        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.addWidget(self.rb_beast)
        hl.addWidget(self.rb_monster)
        grid.addWidget(wrap, 0, 1, 1, 3)

        # 野兽级别
        self.beast_label = QLabel("野兽级别")
        grid.addWidget(self.beast_label, 1, 0)
        self.beast_wrap = QWidget()
        bl = QHBoxLayout(self.beast_wrap)
        bl.setContentsMargins(0, 0, 0, 0)
        self.beast_30 = QCheckBox("30级")
        self.beast_30.setChecked(True)
        self.beast_26 = QCheckBox("26级")
        for w in (self.beast_30, self.beast_26):
            bl.addWidget(w)
        grid.addWidget(self.beast_wrap, 1, 1, 1, 3)

        # 巨兽级别
        self.monster_label = QLabel("巨兽级别")
        grid.addWidget(self.monster_label, 2, 0)
        self.monster_wrap = QWidget()
        ml = QHBoxLayout(self.monster_wrap)
        ml.setContentsMargins(0, 0, 0, 0)
        self.mon_8 = QCheckBox("8级")
        self.mon_7 = QCheckBox("7级")
        self.mon_6 = QCheckBox("6级")
        self.mon_5 = QCheckBox("5级")
        for w in (self.mon_8, self.mon_7, self.mon_6, self.mon_5):
            ml.addWidget(w)
        grid.addWidget(self.monster_wrap, 2, 1, 1, 3)
        # 默认隐藏巨兽选项
        self.monster_label.hide()
        self.monster_wrap.hide()

        # 编队（两排显示：1-4 | 5-8）
        grid.addWidget(QLabel("编队"), 3, 0)
        team_wrap = QWidget()
        tl = QVBoxLayout(team_wrap)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        row1 = QWidget(); r1 = QHBoxLayout(row1); r1.setContentsMargins(0,0,0,0)
        row2 = QWidget(); r2 = QHBoxLayout(row2); r2.setContentsMargins(0,0,0,0)
        self.team_cbs: List[QCheckBox] = []
        for i in range(1, 9):
            cb = QCheckBox(f"{i}队")
            if i <= 2:
                cb.setChecked(True)
            self.team_cbs.append(cb)
            (r1 if i <= 4 else r2).addWidget(cb)
        tl.addWidget(row1)
        tl.addWidget(row2)
        grid.addWidget(team_wrap, 3, 1, 1, 3)

        # 参数
        grid.addWidget(QLabel("循环次数"), 4, 0)
        self.ed_loops = QLineEdit("1")
        self.ed_loops.setFixedWidth(60)
        grid.addWidget(self.ed_loops, 4, 1)
        grid.addWidget(QLabel("步间隔(s)"), 4, 2)
        self.ed_step = QLineEdit("0.10")
        self.ed_step.setFixedWidth(80)
        grid.addWidget(self.ed_step, 4, 3)
        grid.addWidget(QLabel("体力罐头"), 5, 0)
        self.ed_can = QLineEdit("0")
        self.ed_can.setFixedWidth(60)
        grid.addWidget(self.ed_can, 5, 1)

        # 开始
        self.btn = QPushButton("开始打野")
        grid.addWidget(self.btn, 6, 0, 1, 4)
        self.btn._qt_start_handler = self._on_start
        self.btn.clicked.connect(self._on_start)

    def _update_hunt_type(self):
        """切换打野类型时，显示/隐藏对应级别选项"""
        try:
            if self.rb_beast.isChecked():
                self.beast_label.show()
                self.beast_wrap.show()
                self.monster_label.hide()
                self.monster_wrap.hide()
            else:
                self.beast_label.hide()
                self.beast_wrap.hide()
                self.monster_label.show()
                self.monster_wrap.show()
        except Exception:
            pass

    def _on_start(self):
        hunt_type = "beast" if self.rb_beast.isChecked() else "monster"
        beast_levels = [
            30 if self.beast_30.isChecked() else None,
            26 if self.beast_26.isChecked() else None
        ]
        beast_levels = [x for x in beast_levels if x]
        monster_levels = []
        if self.mon_8.isChecked():
            monster_levels.append(8)
        if self.mon_7.isChecked():
            monster_levels.append(7)
        if self.mon_6.isChecked():
            monster_levels.append(6)
        if self.mon_5.isChecked():
            monster_levels.append(5)
        teams = [i + 1 for i, cb in enumerate(self.team_cbs) if cb.isChecked()]
        try:
            loops = int(self.ed_loops.text().strip() or "1")
        except:
            loops = 1
        try:
            step = float(self.ed_step.text().strip() or "0.10")
        except:
            step = 0.10
        try:
            cans = int(self.ed_can.text().strip() or "0")
        except:
            cans = 0

        if hunt_type == "beast" and not beast_levels:
            self._toast("请至少选择一个野兽级别")
            return
        if hunt_type == "monster" and not monster_levels:
            self._toast("请至少选择一个巨兽级别")
            return
        if not teams:
            self._toast("请至少选择一个编队")
            return

        def runner(should_stop):
            run_sweep_hunt(
                self.app, self.serial, hunt_type,
                beast_levels=beast_levels,
                monster_levels=monster_levels,
                teams=teams,
                can_count=cans,
                toast=self._toast, log=self._log,
                loop_count=loops, should_stop=should_stop,
                step_delay=step, threshold=None, verbose=False,
            )

        if bool(self.app.cfg.get("global_mode", False)):
            for t in list(self.app.device_tabs.values()):
                box = getattr(t, "box_hunt", None)
                if box and hasattr(box, "btn"):
                    # 复用当前参数，但面向各自设备执行
                    def make_runner(tt: "DeviceTabQt"):
                        def r(should_stop):
                            run_sweep_hunt(
                                self.app, tt.serial, hunt_type,
                                beast_levels=beast_levels,
                                monster_levels=monster_levels,
                                teams=teams, can_count=cans,
                                toast=tt._toast,
                                log=lambda m: tt._sig.device_log.emit(m),
                                loop_count=loops, should_stop=should_stop,
                                step_delay=step, threshold=None, verbose=False,
                            )
                        return r
                    t._start_task_with_button("hunt", box.btn, make_runner(t))
        else:
            self._start_with_button("hunt", self.btn, runner)

