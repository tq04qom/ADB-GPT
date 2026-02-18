
"""
toast.py — 全局静默 Toast
右下角弹出、无提示音、默认 2 秒自动关闭；支持多条消息错位堆叠。
用法：
    from mumu_adb_controller.ui.toast import show_toast
    show_toast(root=self.winfo_toplevel(), text="操作完成", ms=2000)
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional

# 在 root 上记录当前活跃的 toast 弹窗，避免重叠
_TOAST_KEY = "_active_toasts"

def _get_active_list(root: tk.Misc):
    lst = getattr(root, _TOAST_KEY, None)
    if lst is None:
        lst = []
        setattr(root, _TOAST_KEY, lst)
    # 清理已销毁的
    alive = []
    for t in lst:
        try:
            if t.winfo_exists():
                alive.append(t)
        except Exception:
            pass
    root.__dict__[_TOAST_KEY] = alive
    return alive

def show_toast(root: tk.Misc, text: str, ms: int = 2000, width: int = 360, height: int = 80, margin: int = 20):
    """
    静默 Toast：右下角弹出，自动在 ms 毫秒后关闭。
    - root: Tk/Toplevel（用于定位；传入 None 将直接返回）
    - text: 提示文本
    - ms:   存活时长（毫秒），默认 2000
    - width/height: 弹窗大小（像素）
    - margin: 边距（像素）
    """
    if not root:
        return

    try:
        # 计算位置（支持多条错位堆叠）
        root.update_idletasks()
        rw, rh = root.winfo_width(), root.winfo_height()
        rx, ry = root.winfo_rootx(), root.winfo_rooty()

        active = _get_active_list(root)
        # 为每个活跃 toast 预留 8px 间距，越晚创建越靠上
        offset_y = (len(active)) * (height + 8)

        x = rx + rw - width - margin
        y = ry + rh - height - margin - offset_y
        if y < ry + margin:
            # 如果堆叠超出顶边，强制在底部（不继续堆叠）
            y = ry + rh - height - margin

        toast = tk.Toplevel(root)
        toast.overrideredirect(True)        # 去边框
        toast.attributes("-topmost", True)  # 置顶
        try:
            # 在支持透明度的平台可用，失败则忽略
            toast.attributes("-alpha", 0.97)
        except Exception:
            pass

        # 暗色背景 + 圆角感（通过留白模拟，避免复杂 shape）
        frm = ttk.Frame(toast, padding=12)
        frm.pack(fill="both", expand=True)
        lbl = ttk.Label(frm, text=str(text), wraplength=width - 24, justify="left")
        lbl.pack(fill="both", expand=True)

        # 放到右下角
        toast.geometry(f"{width}x{height}+{x}+{y}")

        # 记录到活跃列表
        active.append(toast)

        def _on_destroy(_=None):
            # 从活跃列表移除本 toast
            lst = _get_active_list(root)
            try:
                lst.remove(toast)
            except ValueError:
                pass

        toast.bind("<Destroy>", _on_destroy)

        # 自动关闭
        toast.after(int(ms), toast.destroy)

        # 禁止抢焦点：避免影响当前输入
        try:
            toast.attributes("-disabled", True)
        except Exception:
            pass

        # 鼠标点击即可提前关闭（可选）
        toast.bind("<Button-1>", lambda e: toast.destroy())

        return toast
    except Exception:
        # 静默失败，不抛异常
        return None
