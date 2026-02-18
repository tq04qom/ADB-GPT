from typing import Optional
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel

class ResourceCoordsDialog(QDialog):
    """
    简单的资源坐标编辑对话框：每行 x:y:备注名:攻击轮次
    - 读取/写入来自 App 配置（cfg['attack_coords'][serial]）
    - 调用方负责持久化保存
    """
    def __init__(self, parent, serial: str, initial_text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑资源坐标（每行：x:y:备注名:攻击轮次）")
        self.setModal(True)
        self.resize(560, 380)
        self.serial = serial
        self._result_text: Optional[str] = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel("格式：每行 x:y:备注名:攻击轮次，例如 123:456:木头点A:2"))
        self.text = QTextEdit(self)
        self.text.setPlainText(initial_text or "")
        root.addWidget(self.text, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _on_ok(self) -> None:
        self._result_text = (self.text.toPlainText() or "").strip()
        self.accept()

    def result_text(self) -> Optional[str]:
        return self._result_text

