"""
资源面板
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox,
    QComboBox, QLabel
)

from .base_panel import BasePanel

if TYPE_CHECKING:
    from ..device_tab_qt import DeviceTabQt


class ResourcesPanel(BasePanel):
    """资源面板"""

    def __init__(self, tab: "DeviceTabQt"):
        super().__init__(tab)
        try:
            setattr(self.tab, "box_resources", self)
        except Exception:
            pass
        box = QGroupBox("资源")
        root = QVBoxLayout(self)
        root.addWidget(box)

        # 资源攻击
        attack_box = QGroupBox("资源攻击（仅当前设备）")
        root.addWidget(attack_box)
        row = QHBoxLayout()
        attack_box.setLayout(row)
        self.btn_edit_coords = QPushButton("编辑资源坐标")
        self.attack_btn = QPushButton("打资源")
        row.addWidget(self.btn_edit_coords)
        row.addWidget(self.attack_btn)

        # 超时处理：中文显示 <-> 英文码
        self.attack_timeout_display_map = {
            "continue": "继续本坐标",
            "skip": "跳过本坐标",
            "abort": "终止任务"
        }
        self.attack_timeout_reverse_map = {
            v: k for k, v in self.attack_timeout_display_map.items()
        }
        row.addWidget(QLabel("等待超时："))
        self.attack_timeout_cb = QComboBox()
        self.attack_timeout_cb.addItems(list(self.attack_timeout_display_map.values()))
        try:
            current_code = self.app.cfg.get("attack_on_timeout", "continue")
            self.attack_timeout_cb.setCurrentText(
                self.attack_timeout_display_map.get(current_code, "继续本坐标")
            )
        except Exception:
            pass

        def _on_timeout_changed():
            try:
                label = self.attack_timeout_cb.currentText()
                code = self.attack_timeout_reverse_map.get(label, "continue")
                self.app.cfg = self.app.config_mgr.load() or {}
                self.app.cfg["attack_on_timeout"] = code
                self.app.config_mgr.save(self.app.cfg)
            except Exception:
                pass

        self.attack_timeout_cb.currentIndexChanged.connect(_on_timeout_changed)
        row.addWidget(self.attack_timeout_cb)

        # 绑定按钮
        self.btn_edit_coords.clicked.connect(self._on_edit_coords)
        self.attack_btn._qt_start_handler = self._on_attack
        self.attack_btn.clicked.connect(self._on_attack)

        # 预加载 coords 文本
        try:
            self.attack_coords_text = (
                self.app.cfg.get("attack_coords", {}) or {}
            ).get(self.serial, "")
        except Exception:
            self.attack_coords_text = ""

        # 资源采集（预留占位，后续实现）
        placeholder = QGroupBox("资源采集（即将支持）")
        root.addWidget(placeholder)

    def _on_edit_coords(self):
        from PySide6.QtWidgets import QDialog
        from ..dialogs.resource_coords_dialog_qt import ResourceCoordsDialog
        dlg = ResourceCoordsDialog(
            self, self.serial,
            initial_text=getattr(self, "attack_coords_text", "")
        )
        if dlg.exec() == QDialog.Accepted:
            text = dlg.result_text() or ""
            self.attack_coords_text = text
            try:
                cfg = self.app.config_mgr.load() or {}
                cfg.setdefault("attack_coords", {})
                cfg["attack_coords"][self.serial] = text
                self.app.config_mgr.save(cfg)
                self.app.cfg = cfg
            except Exception:
                pass
            self._toast("已保存资源坐标（已持久化）")

    def _on_attack(self):
        from mumu_adb_controller.ui.tasks.attack_resources import parse_coords_text, run_attack_resources
        coords = parse_coords_text(getattr(self, "attack_coords_text", ""))
        if not coords:
            self._toast("请先点击'编辑资源坐标'并填写坐标\n每行：x:y:备注名:攻击轮次")
            return
        try:
            remark = (
                self.app.cfg.get("notes", {}) or {}
            ).get(self.serial) or self.serial
        except Exception:
            remark = self.serial

        # 非阻塞提醒：不再使用模态确认框，直接开始执行
        names = [n for (_, _, n, _) in coords]
        self._toast("将执行'打资源'：\n  - " + "\n  - ".join(names))

        def runner(should_stop):
            try:
                sel_label = self.attack_timeout_cb.currentText()
                on_timeout = self.attack_timeout_reverse_map.get(
                    sel_label,
                    self.app.cfg.get("attack_on_timeout", "continue")
                )
            except Exception:
                on_timeout = self.app.cfg.get("attack_on_timeout", "continue")
            run_attack_resources(
                self.app, self.serial, coords,
                toast=self._toast, log=self._log,
                should_stop=should_stop,
                threshold=None, verbose=False,
                on_timeout=on_timeout
            )

        self._start_with_button("attack_resources", self.attack_btn, runner)

