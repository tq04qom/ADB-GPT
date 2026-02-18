# mumu_adb_controller/ui/theme.py
import tkinter as tk
from tkinter import ttk

# 仅做淡化底色和卡片边框；所有文字统一黑色
PANEL_BG = "#F6F7F9"   # 浅灰背景（可改为纯白 "#FFFFFF"）
CARD_BG  = "#FFFFFF"
BORDER   = "#E5E7EB"

def apply_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        if style.theme_use() in ("classic", "default"):
            style.theme_use("clam")
    except Exception:
        pass

    try:
        root.configure(bg=PANEL_BG)
    except Exception:
        pass

    # Notebook：压缩左右边距与标签内边距，提升可视容量
    style.configure("TNotebook", background=PANEL_BG, tabmargins=[3, 1, 3, 0])
    style.configure("TNotebook.Tab",
                    padding=(4, 1),
                    font=("Segoe UI", 8),
                    background="#E9ECEF",
                    foreground="black")
    style.map("TNotebook.Tab",
              background=[("selected", "#D9D9D9"), ("!selected", "#E9ECEF")],
              foreground=[("selected", "black"), ("!selected", "black")],
              font=[("selected", ("Segoe UI", 8, "bold")),
                    ("!selected", ("Segoe UI", 8))])

    # 隐藏页签用的 Notebook 样式：不渲染任何 Tab
    try:
        style.layout("Hidden.TNotebook.Tab", [])
        style.configure("Hidden.TNotebook", background=PANEL_BG, tabmargins=[0, 0, 0, 0])
    except Exception:
        pass

    # 卡片式 Labelframe（标题文字也为黑色）
    style.configure("Card.TLabelframe",
                    background=CARD_BG,
                    bordercolor=BORDER,
                    relief="solid",
                    borderwidth=1)
    style.configure("Card.TLabelframe.Label",
                    background=CARD_BG,
                    foreground="black",
                    font=("Segoe UI", 10, "bold"))

    # 卡片容器
    style.configure("Card.TFrame",
                    background=CARD_BG,
                    bordercolor=BORDER,
                    relief="solid",
                    borderwidth=1)

    # 标签与输入控件
    style.configure("TLabel", foreground="black", background=CARD_BG)
    style.configure("Subtle.TLabel", foreground="black", background=CARD_BG)  # 不再用灰字
    style.configure("TEntry", padding=(6, 4))
    style.configure("TCombobox", padding=(6, 4))

    # 按钮：文字为黑色；底色用浅灰，按下/悬停略深
    style.configure("Accent.TButton",
                    padding=(14, 8),
                    font=("Segoe UI", 10, "bold"),
                    foreground="black",
                    background="#E0E0E0")
    style.map("Accent.TButton",
              background=[("active", "#D0D0D0"), ("pressed", "#C8C8C8")])

    style.configure("TButton",
                    padding=(12, 6),
                    foreground="black",
                    background="#EFEFEF")
    style.map("TButton",
              background=[("active", "#E3E3E3"), ("pressed", "#DADADA")])

    # 小号按钮样式（用于顶栏，减少占用）
    style.configure("Small.TButton",
                    padding=(3, 1),
                    font=("Segoe UI", 8),
                    foreground="black",
                    background="#EFEFEF")
    style.configure("Small.Accent.TButton",
                    padding=(4, 2),
                    font=("Segoe UI", 8, "bold"),
                    foreground="black",
                    background="#E0E0E0")

    # 运行中按钮（深蓝色）——为避免平台主题忽略背景，显式映射全部常见状态
    style.configure("Running.TButton",
                    padding=(12, 6),
                    foreground="white",
                    background="#0D47A1")
    style.map("Running.TButton",
              background=[
                  ("!disabled", "#0D47A1"),
                  ("active",   "#0B3D91"),
                  ("pressed",  "#09367F"),
                  ("disabled", "#6B7280")
              ],
              foreground=[
                  ("!disabled", "white"),
                  ("disabled",  "#E5E7EB")
              ])

    # 分隔线
    style.configure("TSeparator", background=BORDER)
