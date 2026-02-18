# mumu_adb_controller/tools/ui_cropper_updated_v2.py
# 更新版本：增强路径验证和错误处理
# 独立工具：从 ADB 拉取截图或打开本地图片，框选后保存到 pic/ 目录（新建或覆盖）
# 依赖：Pillow（pip install pillow）
# 新增：模板匹配（检查 pic/ 中图片是否存在于当前 UI），显示置信度和坐标；
#      自定义"静默"Toast 弹窗（自动 3 秒关闭，无系统提示音）。
# 可选依赖（更快）：opencv-python（pip install opencv-python）

import os
import io
import sys
import subprocess
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, List

# ---------- 冻结安全 res_path：优先使用集中管理，失败则本地兜底 ----------
try:
    from mumu_adb_controller.common.pathutil import res_path
except Exception:
    def _app_base_dir():
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    def res_path(*parts: str):
        return os.path.join(_app_base_dir(), *parts)

# Pillow 用于图片解码/缩放
try:
    from PIL import Image, ImageTk, ImageOps
except Exception:
    print("缺少 Pillow，请先安装：pip install pillow")
    sys.exit(1)

# 尝试使用 numpy / opencv 以提升匹配速度与精度
_cv2 = None
_np = None
try:
    import numpy as _np
    _np.seterr(all="ignore")
except Exception:
    _np = None

try:
    import cv2 as _cv2
except Exception:
    _cv2 = None

# 可选：系统截图与窗口管理
try:
    import pyautogui as _pya
except Exception:
    _pya = None
try:
    import pygetwindow as _gw
except Exception:
    _gw = None

# Windows DPI 辅助
_is_win = (os.name == "nt")
_dpi_awared = False

def _ensure_dpi_awareness():
    global _dpi_awared
    if not _is_win or _dpi_awared:
        return
    try:
        import ctypes
        # 优先 Per-Monitor V2
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception:
        pass
    _dpi_awared = True

def _get_scale_factor() -> float:
    """获取主显示器缩放比例（100% 返回 1.0）。失败时返回 1.0。"""
    if not _is_win:
        return 1.0
    try:
        import ctypes
        # 优先 GetDpiForSystem（Windows 10+）
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            if dpi:
                return max(0.5, min(4.0, dpi / 96.0))
        except Exception:
            pass
        # 退化：通过 shcore.GetScaleFactorForMonitor
        try:
            MONITOR_DEFAULTTOPRIMARY = 1
            pt = ctypes.wintypes.POINT(0, 0)
            hmon = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY)
            scale = ctypes.c_int()
            if hasattr(ctypes.windll, 'shcore') and ctypes.windll.shcore.GetScaleFactorForMonitor(hmon, ctypes.byref(scale)) == 0:
                return max(0.5, min(4.0, scale.value / 100.0))
        except Exception:
            pass
    except Exception:
        pass
    return 1.0

APP_TITLE = "UI 截图裁剪工具 v2（ADB/本地）"
# 统一识别到项目根目录（tools 上两级）以定位 adb/adb.exe
_DEF_CUR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_DEF_CUR))
ADB_DEFAULT = os.path.join(_PROJECT_ROOT, "adb", "adb.exe")

# 修正图片目录路径：指向项目根目录的pic文件夹
def _get_project_pic_dir():
    """获取项目根目录的pic文件夹路径"""
    # 如果当前文件在tools目录中，向上两级到项目根目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir.endswith("tools"):
        # 在tools目录中，向上两级到项目根目录
        project_root = os.path.dirname(os.path.dirname(current_dir))
        return os.path.join(project_root, "pic")
    else:
        # 不在tools目录中，使用res_path
        return res_path("pic")

SAVE_DIR = _get_project_pic_dir()               # 修正：指向项目根目录的pic文件夹
CANVAS_BG   = "#1e1e1e"


class UICropperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x840")
        self.minsize(980, 640)

        # 状态
        self.serial_var = tk.StringVar(value="")
        self.adb_path_var = tk.StringVar(value=ADB_DEFAULT)
        self.zoom_var = tk.DoubleVar(value=1.0)
        self.out_name_var = tk.StringVar(value="new_template.png")
        self.status_var = tk.StringVar(value="就绪")
        self.devices_list = []  # 存储设备列表

        # 模板匹配参数
        self.thr_var = tk.DoubleVar(value=0.85)  # 置信度阈值
        self.match_results = []  # [(name, conf, (x1,y1,x2,y2))]

        # 目录导航
        self.current_dir = SAVE_DIR  # 当前浏览的目录
        self.dir_history = []  # 目录历史

        # 坐标获取模式
        self._coordinate_mode = False
        self._coord_button = None  # 坐标按钮引用

        # 点击模式（ADB tap + 300ms后自动刷新截图）
        self._click_mode = False
        self._click_button = None  # 点击模式按钮引用


        # 原图/显示图对象
        self._orig_img = None          # PIL.Image 原始图
        self._disp_img = None          # PIL.Image 当前显示图（缩放后）
        self._photo = None             # ImageTk.PhotoImage 绑定到 Canvas
        self._disp_scale = 1.0         # 显示图：orig -> disp 的比例（disp = orig * disp_scale）

        # 选择框（在显示图坐标系中）
        self._sel_start = None         # (x,y) 起点（Canvas坐标）
        self._sel_rect = None          # Canvas item id
        self._sel_box = None           # (x1,y1,x2,y2) 显示图坐标系中的选择框

        # 匹配框可视化
        self._match_items = []         # 画布上绘制的匹配方框与标签 item id

        self._build_ui()
        self._ensure_pic_folder()
        self._refresh_pic_list()
        self._bind_events()

        # 启动时显示路径信息
        self._show_startup_info()

    def _show_startup_info(self):
        """启动时显示路径信息"""
        info = f"图片目录: {SAVE_DIR}\n目录存在: {os.path.exists(SAVE_DIR)}"
        if os.path.exists(SAVE_DIR):
            files = [f for f in os.listdir(SAVE_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))]
            info += f"\n图片文件数: {len(files)}"
        self.status_var.set(info)

    # ----------------------- Toast（静默 3 秒自动关闭） -----------------------
    def _toast(self, text: str, ms: int = 3000):
        """显示一个自定义静默 Toast，无系统提示音，ms 毫秒后自动关闭。"""
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        # 放到右下角
        self.update_idletasks()
        sw = self.winfo_rootx() + self.winfo_width()
        sh = self.winfo_rooty() + self.winfo_height()
        w, h = 360, 80
        x = sw - w - 20
        y = sh - h - 40
        toast.geometry(f"{w}x{h}+{x}+{y}")
        frame = ttk.Frame(toast, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        lbl = ttk.Label(frame, text=text, justify="left", wraplength=w-24)
        lbl.pack(fill=tk.BOTH, expand=True)
        toast.after(ms, toast.destroy)

    # ----------------------- UI -----------------------
    def _build_ui(self):
        # 顶栏：ADB、设备序列号、操作
        top = ttk.Frame(self, padding=(8, 8, 8, 4))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="ADB 路径：").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.adb_path_var, width=15).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Button(top, text="列出设备", command=self._list_devices).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(top, text="序列号：").pack(side=tk.LEFT)
        self.serial_combo = ttk.Combobox(top, textvariable=self.serial_var, width=14, state="readonly")
        self.serial_combo.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(top, text="获取截图（ADB）", command=self._load_from_adb).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Button(top, text="打开本地图片…", command=self._open_local_image).pack(side=tk.LEFT)
        # 新增：系统截图（全桌面/窗口），考虑 DPI 缩放并归一化为 100%
        ttk.Button(top, text="桌面截图", command=self._capture_full_desktop).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="窗口截图", command=self._capture_window_pick).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="清空", command=self._clear_canvas).pack(side=tk.LEFT, padx=(6, 0))

        # 中部：左-画布，右-文件/保存/匹配
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 左侧：画布 + 控件
        left = ttk.Frame(main)
        main.add(left, weight=3)

        # 画布（带滚动条）
        canvas_wrap = ttk.Frame(left)
        canvas_wrap.pack(fill=tk.BOTH, expand=True)

        # 创建画布和滚动条
        self.canvas = tk.Canvas(canvas_wrap, bg=CANVAS_BG, highlightthickness=0, bd=0, cursor="tcross")

        # 垂直滚动条
        v_scrollbar = ttk.Scrollbar(canvas_wrap, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=v_scrollbar.set)

        # 水平滚动条
        h_scrollbar = ttk.Scrollbar(canvas_wrap, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=h_scrollbar.set)

        # 布局画布和滚动条
        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        # 配置网格权重
        canvas_wrap.grid_rowconfigure(0, weight=1)
        canvas_wrap.grid_columnconfigure(0, weight=1)

        # 画布工具栏
        tool = ttk.Frame(left)
        tool.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(tool, text="缩放：").pack(side=tk.LEFT)
        self.zoom_scale = ttk.Scale(tool, from_=0.2, to=2.0, variable=self.zoom_var, command=self._on_zoom_change)
        self.zoom_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6))
        ttk.Button(tool, text="1:1", command=lambda: self._set_zoom(1.0)).pack(side=tk.LEFT)
        ttk.Button(tool, text="适应窗口", command=self._fit_to_window).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(tool, text="清除标注", command=self._clear_match_drawings).pack(side=tk.LEFT, padx=(12, 0))

        # 右侧：保存 + 匹配
        right = ttk.Frame(main, padding=(8, 0, 0, 0))
        main.add(right, weight=2)

        save_box = ttk.LabelFrame(right, text="保存到 pic/", padding=10)
        save_box.pack(fill=tk.X)
        ttk.Label(save_box, text="文件名：").grid(row=0, column=0, sticky="w")
        ttk.Entry(save_box, textvariable=self.out_name_var, width=30).grid(row=0, column=1, sticky="we", padx=(6, 0))
        ttk.Button(save_box, text="保存为新文件", command=self._save_crop_as).grid(row=0, column=2, padx=(8, 0))
        save_box.grid_columnconfigure(1, weight=1)

        exist_box = ttk.LabelFrame(right, text="浏览 pic/ 文件和目录", padding=10)
        exist_box.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        # 目录导航栏
        nav_frame = ttk.Frame(exist_box)
        nav_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(nav_frame, text="↑ 上级", command=self._go_parent_dir).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(nav_frame, text="🏠 根目录", command=self._go_root_dir).pack(side=tk.LEFT, padx=(0, 5))
        self.current_path_var = tk.StringVar()
        ttk.Label(nav_frame, textvariable=self.current_path_var, font=("Arial", 8)).pack(side=tk.LEFT, padx=(10, 0))

        self.pic_list = tk.Listbox(exist_box, height=10)
        self.pic_list.pack(fill=tk.BOTH, expand=True)
        self.pic_list.bind("<Double-Button-1>", self._on_list_double_click)

        # 按钮行
        btn_frame = ttk.Frame(exist_box)
        # 新增：点击模式（ADB tap）
        self._click_button = ttk.Button(btn_frame, text="点击模式(ADB)", command=self._toggle_click_mode)
        self._click_button.pack(side=tk.LEFT, padx=(6, 0))

        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="覆盖所选", command=self._overwrite_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="单个匹配", command=self._match_single_file).pack(side=tk.LEFT, padx=(0, 5))
        self._coord_button = ttk.Button(btn_frame, text="点击获取坐标", command=self._toggle_coordinate_mode)
        self._coord_button.pack(side=tk.LEFT)

        # 匹配功能区
        match_box = ttk.LabelFrame(right, text="模板匹配：检查当前目录图片是否存在于UI中", padding=10)
        match_box.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        thr_row = ttk.Frame(match_box)
        thr_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(thr_row, text="置信度阈值：").pack(side=tk.LEFT)
        thr_scale = ttk.Scale(thr_row, from_=0.5, to=0.99, variable=self.thr_var)
        thr_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        self.thr_val_lbl = ttk.Label(thr_row, text=f"{self.thr_var.get():.2f}")  # 修正：移除 lambda
        self.thr_val_lbl.pack(side=tk.LEFT)
        def _upd_thr_lbl(*_):
            self.thr_val_lbl.configure(text=f"{self.thr_var.get():.2f}")
        self.thr_var.trace_add("write", lambda *args: _upd_thr_lbl())

        btn_row = ttk.Frame(match_box)
        btn_row.pack(fill=tk.X, pady=(4, 6))
        ttk.Button(btn_row, text="批量匹配", command=self._run_template_matching).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="清空结果", command=self._clear_match_results).pack(side=tk.LEFT, padx=(8, 0))

        self.result_list = tk.Listbox(match_box, height=10)
        self.result_list.pack(fill=tk.BOTH, expand=True)
        self.result_list.bind("<Double-Button-1>", self._jump_to_result)

        # 状态栏
        status = ttk.Frame(self, padding=(8, 4, 8, 8))
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_lbl = ttk.Label(status, textvariable=self.status_var, anchor="w")
        self.status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(status, text="小技巧：拖拽框选区域；Ctrl+S 快速保存；坐标模式下点击获取坐标").pack(side=tk.RIGHT)

    def _bind_events(self):
        # Canvas 鼠标事件（拖拽框选）
        self.canvas.bind("<Button-1>", self._on_canvas_down)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_up)
        self.canvas.bind("<Motion>", self._on_canvas_motion)  # 鼠标移动事件
        # 窗口大小变化时，适配预览
        self.canvas.bind("<Configure>", lambda e: self._refresh_display_image(redraw_only=True))
        # 快捷键
        self.bind("<Control-s>", lambda e: self._save_crop_as())

    def _ensure_pic_folder(self):
        """确保图片目录存在，如果创建失败则显示错误"""
        try:
            os.makedirs(SAVE_DIR, exist_ok=True)
            if not os.path.exists(SAVE_DIR):
                raise Exception(f"无法创建目录: {SAVE_DIR}")
        except Exception as e:
            messagebox.showerror("目录错误", f"无法访问图片目录:\n{SAVE_DIR}\n错误: {e}")
            self.status_var.set(f"目录错误: {e}")

    def _refresh_pic_list(self):
        """刷新图片列表，支持子目录浏览"""
        self.pic_list.delete(0, tk.END)

        # 更新当前路径显示
        rel_path = os.path.relpath(self.current_dir, SAVE_DIR)
        if rel_path == ".":
            self.current_path_var.set("📁 pic/")
        else:
            self.current_path_var.set(f"📁 pic/{rel_path}/")

        if not os.path.exists(self.current_dir):
            self.pic_list.insert(tk.END, "⚠️ 目录不存在")
            return

        dirs = []
        files = []
        try:
            for name in os.listdir(self.current_dir):
                full_path = os.path.join(self.current_dir, name)
                if os.path.isdir(full_path):
                    dirs.append(name)
                elif name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
                    files.append(name)

            dirs.sort()
            files.sort()

            # 先显示目录
            for d in dirs:
                self.pic_list.insert(tk.END, f"📁 {d}/")

            # 再显示文件
            if not files and not dirs:
                self.pic_list.insert(tk.END, "📂 目录为空")
            else:
                for f in files:
                    self.pic_list.insert(tk.END, f)

        except Exception as e:
            self.pic_list.insert(tk.END, f"⚠️ 读取错误: {e}")

    def _go_parent_dir(self):
        """返回上级目录"""
        parent = os.path.dirname(self.current_dir)
        if parent and len(parent) >= len(SAVE_DIR):
            self.current_dir = parent
            self._refresh_pic_list()

    def _go_root_dir(self):
        """返回根目录"""
        self.current_dir = SAVE_DIR
        self._refresh_pic_list()

    def _on_list_double_click(self, event):
        """列表双击事件：进入目录或预览文件"""
        sel = self.pic_list.curselection()
        if not sel:
            return

        item = self.pic_list.get(sel[0])
        if item.startswith("📁 ") and item.endswith("/"):
            # 进入子目录
            dir_name = item[2:-1]  # 去掉 "📁 " 和 "/"
            new_dir = os.path.join(self.current_dir, dir_name)
            if os.path.exists(new_dir):
                self.current_dir = new_dir
                self._refresh_pic_list()
        elif not item.startswith(("⚠️", "📂")):
            # 预览图片文件
            self._preview_selected_file()

    def _preview_selected_file(self):
        """预览选中的图片文件"""
        sel = self.pic_list.curselection()
        if not sel:
            return

        item = self.pic_list.get(sel[0])
        if item.startswith(("📁", "⚠️", "📂")):
            return

        file_path = os.path.join(self.current_dir, item)
        if os.path.exists(file_path):
            try:
                self._load_image_from_path(file_path)
                self._toast(f"已加载: {item}")
            except Exception as e:
                messagebox.showerror("加载失败", f"无法加载图片：\n{e}")

    def _match_single_file(self):
        """单个文件模板匹配"""
        sel = self.pic_list.curselection()
        if not sel:
            messagebox.showwarning("单个匹配", "请先选择一个图片文件")
            return

        if not self._orig_img:
            messagebox.showwarning("单个匹配", "请先加载目标图片")
            return

        item = self.pic_list.get(sel[0])
        if item.startswith(("📁", "⚠️", "📂")):
            messagebox.showwarning("单个匹配", "请选择图片文件，不是目录")
            return

        template_path = os.path.join(self.current_dir, item)
    def _toggle_click_mode(self):
        """切换点击模式：在图上点击 -> ADB tap 同步到设备，300ms后自动刷新截图"""
        # 与坐标模式互斥
        if self._click_mode:
            self._click_mode = False
            if self._click_button:
                self._click_button.config(text="点击模式(ADB)", style="")
            self.canvas.config(cursor="tcross")
            self.status_var.set("已退出点击模式")
            self._toast("已退出点击模式")
        else:
            self._click_mode = True
            # 退出坐标模式
            if self._coordinate_mode:
                self._coordinate_mode = False
                if self._coord_button:
                    self._coord_button.config(text="点击获取坐标", style="")
            if self._click_button:
                self._click_button.config(text="退出点击模式", style="Accent.TButton")
            self.canvas.config(cursor="hand2")
            self.status_var.set("点击模式：单击图片将发送 ADB tap 并自动刷新截图")
            self._toast("点击模式已启用\n单击图片将发送 ADB tap 并在 300ms 后自动刷新截图")

    def _adb_tap(self, x: int, y: int):
        serial = (self.serial_var.get() or "").strip()
        if not serial:
            messagebox.showwarning("点击模式", "请先从顶部选择设备并获取一次 ADB 截图")
            return False
        adb = (self.adb_path_var.get() or ADB_DEFAULT).strip()
        if not os.path.isfile(adb) and os.path.basename(adb).lower() != "adb.exe":
            adb = "adb"
        try:
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            p = subprocess.run([adb, "-s", serial, "shell", "input", "tap", str(int(x)), str(int(y))],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8, creationflags=creation)
            return p.returncode == 0
        except Exception:
            return False

        if not os.path.exists(template_path):
            messagebox.showerror("单个匹配", "文件不存在")
            return

        try:
            self._match_single_template(template_path, item)
        except Exception as e:
            messagebox.showerror("单个匹配", f"匹配失败：\n{e}")

    def _toggle_coordinate_mode(self):
        """切换坐标获取模式"""
        if not self._orig_img:
            messagebox.showwarning("获取坐标", "请先加载一张图片")
            return

        if self._coordinate_mode:
            # 退出坐标模式
            self._coordinate_mode = False
            self._coord_button.config(text="点击获取坐标", style="")
            self.canvas.config(cursor="tcross")
            self.status_var.set("已退出坐标模式")
            self._toast("已退出坐标模式")
        else:
            # 进入坐标模式
            self._coordinate_mode = True
            self._coord_button.config(text="退出坐标模式", style="Accent.TButton")
            self.canvas.config(cursor="crosshair")
            self.status_var.set("坐标模式：点击图片任意位置获取坐标和颜色")
            self._toast("坐标模式已启用\n点击图片任意位置获取坐标和颜色\n坐标将自动复制到剪贴板")

    def _match_single_template(self, template_path, template_name):
        """执行单个模板匹配"""
        try:
            # 加载模板图片
            template_img = Image.open(template_path).convert("RGBA")

            if _cv2 and _np:
                # 使用OpenCV进行匹配
                self._opencv_single_match(template_img, template_name)
            else:
                # 使用PIL进行简单匹配
                self._pil_single_match(template_img, template_name)

        except Exception as e:
            raise Exception(f"模板匹配失败: {str(e)}")

    def _opencv_single_match(self, template_img, template_name):
        """使用OpenCV进行单个模板匹配"""
        # 转换为numpy数组
        orig_array = _np.array(self._orig_img.convert("RGB"))
        template_array = _np.array(template_img.convert("RGB"))

        # 转换为灰度
        orig_gray = _cv2.cvtColor(orig_array, _cv2.COLOR_RGB2GRAY)
        template_gray = _cv2.cvtColor(template_array, _cv2.COLOR_RGB2GRAY)

        # 模板匹配
        result = _cv2.matchTemplate(orig_gray, template_gray, _cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = _cv2.minMaxLoc(result)

        # 清除之前的结果
        self.match_results.clear()

        threshold = self.thr_var.get()
        if max_val >= threshold:
            # 计算匹配框
            h, w = template_gray.shape
            x1, y1 = max_loc
            x2, y2 = x1 + w, y1 + h

            self.match_results.append((template_name, max_val, (x1, y1, x2, y2)))
            self._update_match_results()
            self._draw_match_boxes()
            self._toast(f"找到匹配: {template_name}\n置信度: {max_val:.3f}\n位置: ({x1}, {y1})")
        else:
            self._toast(f"未找到匹配: {template_name}\n最高置信度: {max_val:.3f} < {threshold:.3f}")

    def _pil_single_match(self, template_img, template_name):
        """使用PIL进行简单的单个模板匹配"""
        self._toast(f"正在匹配 {template_name}...\n(建议安装OpenCV以获得更好效果)")
        # 简化的匹配逻辑，这里只是示例
        messagebox.showinfo("提示", "建议安装OpenCV以获得更好的模板匹配效果\npip install opencv-python")

    def _get_click_coordinates(self, event):
        """获取点击位置的坐标"""
        if not self._orig_img or not self._disp_img:
            return

        # 获取Canvas坐标（考虑滚动偏移）
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # 计算原图坐标
        orig_x = int(canvas_x / self._disp_scale)
        orig_y = int(canvas_y / self._disp_scale)

        # 确保坐标在有效范围内
        orig_x = max(0, min(orig_x, self._orig_img.width - 1))
        orig_y = max(0, min(orig_y, self._orig_img.height - 1))

        # 获取像素颜色
        try:
            pixel = self._orig_img.getpixel((orig_x, orig_y))
            if len(pixel) >= 3:
                r, g, b = pixel[:3]
                hex_color = f"#{r:02x}{g:02x}{b:02x}"
                color_info = f"RGB({r},{g},{b}) {hex_color}"
            else:
                color_info = "无法获取颜色"
        except:
            color_info = "颜色获取失败"

        # 在点击位置绘制标记
        self._draw_coordinate_marker(canvas_x, canvas_y, orig_x, orig_y, color_info)

        # 显示坐标信息
        coord_text = f"({orig_x}, {orig_y})"
        self.status_var.set(f"坐标: {coord_text} | 颜色: {color_info} | 继续点击或按按钮退出")

        # 复制坐标到剪贴板
        self.clipboard_clear()
        self.clipboard_append(coord_text)

        # 显示Toast提示
        self._toast(f"📍 坐标: {coord_text}\n🎨 颜色: {color_info}\n📋 已复制到剪贴板")

    def _draw_coordinate_marker(self, canvas_x, canvas_y, orig_x, orig_y, color_info):
        """在点击位置绘制坐标标记"""
        # 清除之前的坐标标记
        self.canvas.delete("coord_marker")

        # 绘制十字标记
        marker_size = 10
        self.canvas.create_line(canvas_x - marker_size, canvas_y,
                               canvas_x + marker_size, canvas_y,
                               fill="#ff0000", width=2, tags="coord_marker")
        self.canvas.create_line(canvas_x, canvas_y - marker_size,
                               canvas_x, canvas_y + marker_size,
                               fill="#ff0000", width=2, tags="coord_marker")

        # 绘制圆形标记
        circle_size = 5
        self.canvas.create_oval(canvas_x - circle_size, canvas_y - circle_size,
                               canvas_x + circle_size, canvas_y + circle_size,
                               outline="#ff0000", width=2, tags="coord_marker")

        # 绘制坐标标签
        coord_text = f"({orig_x}, {orig_y})"
        label_x = canvas_x + 15
        label_y = canvas_y - 15

        # 标签背景
        text_width = len(coord_text) * 7 + 10
        text_height = 20
        self.canvas.create_rectangle(label_x, label_y - text_height//2,
                                    label_x + text_width, label_y + text_height//2,
                                    fill="#000000", outline="#ff0000", width=1,
                                    tags="coord_marker")

        # 标签文字
        self.canvas.create_text(label_x + 5, label_y, text=coord_text,
                               fill="#ff0000", anchor="w", font=("Arial", 9, "bold"),
                               tags="coord_marker")

    def _on_canvas_motion(self, event):
        """鼠标移动事件：在坐标模式下显示实时坐标"""
        if not self._coordinate_mode or not self._orig_img or not self._disp_img:
            return

        # 获取Canvas坐标（考虑滚动偏移）
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # 计算原图坐标
        orig_x = int(canvas_x / self._disp_scale)
        orig_y = int(canvas_y / self._disp_scale)

        # 确保坐标在有效范围内
        if 0 <= orig_x < self._orig_img.width and 0 <= orig_y < self._orig_img.height:
            # 获取像素颜色
            try:
                pixel = self._orig_img.getpixel((orig_x, orig_y))
                if len(pixel) >= 3:
                    r, g, b = pixel[:3]
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                    color_info = f"RGB({r},{g},{b}) {hex_color}"
                else:
                    color_info = "无法获取颜色"
            except:
                color_info = "颜色获取失败"

            # 更新状态栏显示实时坐标
            self.status_var.set(f"实时坐标: ({orig_x}, {orig_y}) | 颜色: {color_info} | 点击复制坐标")

    # ----------------------- ADB / 打开图片 -----------------------
    def _list_devices(self):
        adb = self.adb_path_var.get().strip() or "adb"
        try:
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            p = subprocess.run([adb, "devices"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, creationflags=creation)
            out = p.stdout.decode("utf-8", errors="ignore")
            lines = [x.strip() for x in out.splitlines() if x.strip()]
            devices = []
            for line in lines[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])

            # 更新设备下拉框
            self.devices_list = devices
            self.serial_combo['values'] = devices

            if not devices:
                self._show_device_toast("未发现在线设备", 2000)
            else:
                self._show_device_toast(f"发现 {len(devices)} 个在线设备", 2000)
                # 如果有设备，自动选择第一个
                if devices:
                    self.serial_var.set(devices[0])

        except Exception as e:
            self._show_device_toast(f"执行 adb 失败：{e}", 2000)

    def _show_device_toast(self, text: str, ms: int = 2000):
        """显示设备列表的无声弹窗，ms 毫秒后自动关闭"""
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        # 放到右下角
        self.update_idletasks()
        sw = self.winfo_rootx() + self.winfo_width()
        sh = self.winfo_rooty() + self.winfo_height()
        w, h = 360, 80
        x = sw - w - 20
        y = sh - h - 40
        toast.geometry(f"{w}x{h}+{x}+{y}")
        frame = ttk.Frame(toast, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        lbl = ttk.Label(frame, text=text, justify="left", wraplength=w-24)
        lbl.pack(fill=tk.BOTH, expand=True)
        toast.after(ms, toast.destroy)

    def _load_from_adb(self):
        serial = self.serial_var.get().strip()
        if not serial:
            messagebox.showwarning("ADB 截图", "请先输入设备序列号（或点击\"列出设备\"查看）")
            return

        adb = self.adb_path_var.get().strip() or ADB_DEFAULT
        if not os.path.isfile(adb) and os.path.basename(adb).lower() != "adb.exe":
            messagebox.showwarning("ADB 截图", f"未找到 ADB：{adb}\n将尝试使用系统 PATH 中的 adb")
            adb = "adb"

        try:
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            cmd = [adb, "-s", serial, "exec-out", "screencap", "-p"]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25, creationflags=creation)
            if p.returncode != 0 or not p.stdout:
                raise RuntimeError(p.stderr.decode("utf-8", errors="ignore") or "无输出")
            self._load_image_from_bytes(p.stdout)
            # 默认适应窗口显示
            try:
                self.after(0, self._fit_to_window)
            except Exception:
                pass
            self.status_var.set(f"已加载来自 {serial} 的截图（{self._orig_img.width}×{self._orig_img.height}）")
        except subprocess.TimeoutExpired:
            messagebox.showerror("ADB 截图", "ADB 截图超时，请重试或检查设备连接")
        except Exception as e:
            messagebox.showerror("ADB 截图", f"拉取截图失败：\n{e}")

    def _open_local_image(self):
        """打开本地图片文件"""
        path = filedialog.askopenfilename(
            title="选择一张图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("PNG 图片", "*.png"),
                ("JPEG 图片", "*.jpg *.jpeg"),
                ("所有文件", "*.*")
            ]
        )
        if path and os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    self._load_image_from_bytes(f.read())
                self.status_var.set(f"已加载本地图片：{os.path.basename(path)}（{self._orig_img.width}×{self._orig_img.height}）")
            except Exception as e:
                messagebox.showerror("打开图片", f"无法加载图片：\n{e}")
    # ----------------------- 系统截图（桌面/窗口，带DPI归一化） -----------------------
    def _capture_full_desktop(self):
        """系统：全桌面截图，并按 DPI 将图像归一化到 100% 比例。"""
        if _pya is None:
            messagebox.showwarning("系统截图", "需要安装 pyautogui 才能进行系统截图")
            return
        try:
            _ensure_dpi_awareness()
            scale = _get_scale_factor()
            img = _pya.screenshot()
            if scale and abs(scale - 1.0) > 0.01:
                w = max(1, int(round(img.width / scale)))
                h = max(1, int(round(img.height / scale)))
                img = img.resize((w, h), Image.LANCZOS)
                self.status_var.set(f"系统全桌面截图（已按 {scale:.2f} 倍缩放归一化到100%）：{w}×{h}")
            else:
                self.status_var.set(f"系统全桌面截图：{img.width}×{img.height}")
            # 载入到画布
            self._orig_img = img.convert("RGB")
            self._disp_img = None
            self._photo = None
            self._sel_box = None
            self._sel_start = None
            if self._sel_rect:
                self.canvas.delete(self._sel_rect)
                self._sel_rect = None
            self._clear_match_drawings()
            self._clear_match_results()
            self._refresh_display_image()
        except Exception as e:
            messagebox.showerror("系统截图", f"全桌面截图失败：\n{e}")

    def _capture_window_pick(self):
        """系统：选择窗口并截图（按 DPI 归一化）。"""
        if _pya is None or _gw is None:
            messagebox.showwarning("系统截图", "需要安装 pyautogui 和 pygetwindow 才能进行窗口截图")
            return
        try:
            _ensure_dpi_awareness()
            # 收集窗口标题
            titles = []
            try:
                titles = [t for t in _gw.getAllTitles() if t and t.strip()]
            except Exception:
                titles = []
            if not titles:
                messagebox.showwarning("系统截图", "未获取到可用窗口标题")
                return
            # 简单选择对话框
            sel = self._pick_from_list("选择窗口", titles)
            if not sel:
                return
            wins = _gw.getWindowsWithTitle(sel)
            if not wins:
                messagebox.showwarning("系统截图", "未找到窗口实例")
                return
            w = wins[0]
            # 先激活窗口，避免截到其它前台内容
            try:
                w.activate()
            except Exception:
                pass
            time.sleep(0.2)
            # 获取窗口区域（激活后再取，避免位置/大小变动）
            left, top, right, bottom = w.left, w.top, w.right, w.bottom
            width, height = max(1, right - left), max(1, bottom - top)
            # 截图该区域
            img = _pya.screenshot(region=(left, top, width, height))
            scale = _get_scale_factor()
            if scale and abs(scale - 1.0) > 0.01:
                tw = max(1, int(round(img.width / scale)))
                th = max(1, int(round(img.height / scale)))
                img = img.resize((tw, th), Image.LANCZOS)
                self.status_var.set(f"窗口截图（{sel}），已按 {scale:.2f} 倍归一化到100%：{tw}×{th}")
            else:
                self.status_var.set(f"窗口截图（{sel}）：{img.width}×{img.height}")
            # 载入
            self._orig_img = img.convert("RGB")
            self._disp_img = None
            self._photo = None
            self._sel_box = None
            self._sel_start = None
            if self._sel_rect:
                self.canvas.delete(self._sel_rect)
                self._sel_rect = None
            self._clear_match_drawings()
            self._clear_match_results()
            self._refresh_display_image()
        except Exception as e:
            messagebox.showerror("系统截图", f"窗口截图失败：\n{e}")

    def _pick_from_list(self, title: str, items: List[str]) -> Optional[str]:
        """简易列表选择对话框，返回所选项或 None。"""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("520x360")
        listbox = tk.Listbox(dlg)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for it in items:
            listbox.insert(tk.END, it)
        sel_var = {"val": None}
        def _ok():
            try:
                idx = listbox.curselection()
                if idx:
                    sel_var["val"] = listbox.get(idx[0])
            except Exception:
                sel_var["val"] = None
            dlg.destroy()
        def _cancel():
            dlg.destroy()
        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=10, pady=(0,10))
        ttk.Button(btns, text="确定", command=_ok).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btns, text="取消", command=_cancel).pack(side=tk.RIGHT)
        dlg.wait_window()
        return sel_var["val"]


    def _load_image_from_bytes(self, data: bytes):
        """从字节数据加载图片"""
        try:
            img = Image.open(io.BytesIO(data))
            if img.mode != "RGB":
                img = img.convert("RGB")
            self._orig_img = img
            self._disp_img = None
            self._photo = None
            self._sel_box = None
            self._sel_start = None
            if self._sel_rect:
                self.canvas.delete(self._sel_rect)
                self._sel_rect = None
            self._clear_match_drawings()
            self._clear_match_results()
            self._refresh_display_image()
        except Exception as e:
            raise RuntimeError(f"图片解码失败：{e}")

    def _clear_canvas(self):
        """清空画布和状态"""
        self._orig_img = None
        self._disp_img = None
        self._photo = None
        self._sel_box = None
        self._sel_start = None
        if self._sel_rect:
            self.canvas.delete(self._sel_rect)
            self._sel_rect = None
        self.canvas.delete("all")
        self._clear_match_drawings()
        self._clear_match_results()
        # 退出坐标模式
        if self._coordinate_mode:
            self._coordinate_mode = False
            if self._coord_button:
                self._coord_button.config(text="点击获取坐标", style="")
            self.canvas.config(cursor="tcross")
        self.status_var.set("已清空")

    # ----------------------- 缩放与显示 -----------------------
    def _on_zoom_change(self, value):
        """缩放滑块变化回调"""
        self._set_zoom(float(value))

    def _set_zoom(self, scale: float):
        """设置缩放比例"""
        self.zoom_var.set(scale)
        self._refresh_display_image()

    def _fit_to_window(self):
        """适应窗口大小"""
        if not self._orig_img:
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        img_w, img_h = self._orig_img.size
        scale_x = cw / img_w
        scale_y = ch / img_h
        scale = min(scale_x, scale_y, 2.0)  # 最大2倍
        self._set_zoom(scale)

    def _refresh_display_image(self, redraw_only=False):
        """刷新显示图片（缩放、重绘）"""
        if not self._orig_img:
            return

        # 计算显示比例
        scale = self.zoom_var.get()
        if scale <= 0:
            scale = 1.0
            self.zoom_var.set(1.0)

        # 如果仅重绘（窗口大小变化），不重新缩放
        if redraw_only and self._disp_img and abs(self._disp_scale - scale) < 0.01:
            pass
        else:
            # 缩放图片
            w, h = self._orig_img.size
            new_w = int(w * scale)
            new_h = int(h * scale)
            if new_w <= 0 or new_h <= 0:
                return
            self._disp_img = self._orig_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            self._disp_scale = scale

        # 更新画布
        self._photo = ImageTk.PhotoImage(self._disp_img)
        self.canvas.delete("image")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo, tags="image")
        self.canvas.config(scrollregion=(0, 0, self._disp_img.width, self._disp_img.height))

        # 重绘选择框和匹配框
        if self._sel_box:
            self._draw_selection_box()
        if self.match_results:
            self._draw_match_boxes()

    # ----------------------- 选择框操作 -----------------------
    def _on_canvas_down(self, event):
        """鼠标按下：坐标/点击模式或开始选择"""
        if not self._disp_img:
            return

        # 点击模式：转换坐标 -> ADB tap -> 300ms后自动刷新截图
        if self._click_mode:
            # 获取Canvas坐标（考虑滚动偏移）
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)
            # 还原为原图坐标
            scale = self.zoom_var.get() or 1.0
            orig_x = int(canvas_x / scale)
            orig_y = int(canvas_y / scale)
            if orig_x >= 0 and orig_y >= 0 and self._orig_img:
                w, h = self._orig_img.size
                if orig_x < w and orig_y < h:
                    if self._adb_tap(orig_x, orig_y):
                        # 轻提示
                        try:
                            self._toast(f"ADB tap: ({orig_x}, {orig_y})")
                        except Exception:
                            pass
                        # 300ms后刷新截图
                        self.after(300, self._load_from_adb)
            return

        # 坐标获取模式
        if self._coordinate_mode:
            self._get_click_coordinates(event)
            return

        # 正常选择模式
        self._sel_start = (event.x, event.y)
        self._sel_box = None
        if self._sel_rect:
            self.canvas.delete(self._sel_rect)
            self._sel_rect = None

    def _on_canvas_drag(self, event):
        """鼠标拖拽：更新选择框"""
        if not self._sel_start or not self._disp_img:
            return
        x1, y1 = self._sel_start
        x2, y2 = event.x, event.y
        # 限制在图片范围内
        x1 = max(0, min(x1, self._disp_img.width - 1))
        y1 = max(0, min(y1, self._disp_img.height - 1))
        x2 = max(0, min(x2, self._disp_img.width - 1))
        y2 = max(0, min(y2, self._disp_img.height - 1))
        # 绘制选择框
        if self._sel_rect:
            self.canvas.delete(self._sel_rect)
        self._sel_rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff00", width=2, dash=(4, 2))

    def _on_canvas_up(self, event):
        """鼠标释放：完成选择"""
        if not self._sel_start or not self._disp_img:
            return
        x1, y1 = self._sel_start
        x2, y2 = event.x, event.y
        # 限制在图片范围内并确保 x1<=x2, y1<=y2
        x1 = max(0, min(x1, self._disp_img.width - 1))
        y1 = max(0, min(y1, self._disp_img.height - 1))
        x2 = max(0, min(x2, self._disp_img.width - 1))
        y2 = max(0, min(y2, self._disp_img.height - 1))
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        # 最小尺寸检查
        if (x2 - x1) < 4 or (y2 - y1) < 4:
            self._toast("选择区域太小（至少 4×4 像素）")
            if self._sel_rect:
                self.canvas.delete(self._sel_rect)
                self._sel_rect = None
            return
        self._sel_box = (x1, y1, x2, y2)
        self._draw_selection_box()
        self.status_var.set(f"已选择区域：{x2-x1}×{y2-y1} 像素")

    def _draw_selection_box(self):
        """绘制选择框（带坐标标签）"""
        if not self._sel_box:
            return
        x1, y1, x2, y2 = self._sel_box
        # 删除旧的选择框
        if self._sel_rect:
            self.canvas.delete(self._sel_rect)
        # 绘制新选择框
        self._sel_rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff00", width=2, dash=(4, 2))
        # 添加坐标标签
        label_text = f"({x1},{y1})-({x2},{y2})"
        label_bg = self.canvas.create_rectangle(x1, y1-20, x1+len(label_text)*6+10, y1, fill="#000000", outline="#00ff00")
        label = self.canvas.create_text(x1+5, y1-10, text=label_text, fill="#00ff00", anchor="w", font=("Arial", 9))
        self.canvas.addtag_withtag("selection_label", label_bg)
        self.canvas.addtag_withtag("selection_label", label)

    # ----------------------- 保存操作 -----------------------
    def _save_crop_as(self):
        """保存为新文件"""
        if not self._sel_box or not self._orig_img:
            messagebox.showwarning("保存", "请先选择要裁剪的区域")
            return
        name = self.out_name_var.get().strip()
        if not name:
            messagebox.showwarning("保存", "请输入文件名")
            return
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            name += ".png"
        self._save_crop_to_file(name)

    def _overwrite_selected(self):
        """覆盖选中的现有文件"""
        sel = self.pic_list.curselection()
        if not sel:
            messagebox.showwarning("覆盖", "请先选择要覆盖的文件")
            return
        if not self._sel_box or not self._orig_img:
            messagebox.showwarning("覆盖", "请先选择要裁剪的区域")
            return
        name = self.pic_list.get(sel[0])
        if name.startswith("⚠️") or name.startswith("📁"):
            messagebox.showwarning("覆盖", "无法覆盖此项目")
            return
        if messagebox.askyesno("确认覆盖", f"确定要覆盖文件 {name} 吗？"):
            self._save_crop_to_file(name)

    def _save_crop_to_file(self, filename: str):
        """保存裁剪区域到文件"""
        try:
            # 转换显示坐标到原始坐标
            x1, y1, x2, y2 = self._sel_box
            orig_x1 = int(x1 / self._disp_scale)
            orig_y1 = int(y1 / self._disp_scale)
            orig_x2 = int(x2 / self._disp_scale)
            orig_y2 = int(y2 / self._disp_scale)
            # 裁剪
            crop = self._orig_img.crop((orig_x1, orig_y1, orig_x2, orig_y2))
            # 保存到当前目录
            path = os.path.join(self.current_dir, filename)
            crop.save(path, "PNG")
            rel_path = os.path.relpath(self.current_dir, SAVE_DIR)
            dir_name = "pic/" if rel_path == "." else f"pic/{rel_path}/"
            self._toast(f"已保存：{dir_name}{filename}\n尺寸：{crop.width}×{crop.height}")
            self._refresh_pic_list()
        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存图片：\n{e}")

    # ----------------------- 模板匹配 -----------------------
    def _run_template_matching(self):
        """运行模板匹配 - 匹配当前目录下的所有图片"""
        if not self._orig_img:
            messagebox.showwarning("模板匹配", "请先加载一张图片")
            return
        if not os.path.exists(self.current_dir):
            messagebox.showwarning("模板匹配", f"当前目录不存在：{self.current_dir}")
            return

        # 获取当前目录的图片文件列表
        template_files = []
        try:
            for name in os.listdir(self.current_dir):
                if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
                    template_files.append(name)
        except Exception as e:
            messagebox.showerror("模板匹配", f"无法读取当前目录：\n{e}")
            return

        if not template_files:
            rel_path = os.path.relpath(self.current_dir, SAVE_DIR)
            dir_name = "pic/" if rel_path == "." else f"pic/{rel_path}/"
            messagebox.showinfo("模板匹配", f"{dir_name} 目录中没有图片文件")
            return

        self.match_results = []
        threshold = self.thr_var.get()

        # 转换原图为 numpy 数组（用于匹配）
        if _np is None or _cv2 is None:
            messagebox.showwarning("模板匹配", "需要安装 numpy 和 opencv-python 以获得更好的性能")
            return

        try:
            # 转换 PIL Image 为 OpenCV 格式
            screen_cv = _np.array(self._orig_img)
            screen_cv = _cv2.cvtColor(screen_cv, _cv2.COLOR_RGB2BGR)

            for template_name in template_files:
                template_path = os.path.join(self.current_dir, template_name)
                try:
                    # 加载模板图片
                    template = _cv2.imread(template_path, _cv2.IMREAD_COLOR)
                    if template is None:
                        continue

                    # 模板匹配
                    result = _cv2.matchTemplate(screen_cv, template, _cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = _cv2.minMaxLoc(result)

                    if max_val >= threshold:
                        # 计算匹配区域
                        h, w = template.shape[:2]
                        x1, y1 = max_loc
                        x2, y2 = x1 + w, y1 + h
                        self.match_results.append((template_name, max_val, (x1, y1, x2, y2)))

                except Exception as e:
                    print(f"匹配 {template_name} 时出错：{e}")
                    continue

            # 更新结果列表
            self._update_match_results()
            # 绘制匹配框
            self._draw_match_boxes()

            if self.match_results:
                self._toast(f"找到 {len(self.match_results)} 个匹配项")
            else:
                self._toast("未找到匹配项")

        except Exception as e:
            messagebox.showerror("模板匹配", f"匹配过程出错：\n{e}")

    def _update_match_results(self):
        """更新匹配结果列表"""
        self.result_list.delete(0, tk.END)
        for name, conf, (x1, y1, x2, y2) in self.match_results:
            item = f"{name} ({conf:.3f}) @ ({x1},{y1})-({x2},{y2})"
            self.result_list.insert(tk.END, item)

    def _draw_match_boxes(self):
        """在画布上绘制匹配框"""
        self._clear_match_drawings()
        if not self.match_results or not self._disp_img:
            return

        for name, conf, (x1, y1, x2, y2) in self.match_results:
            # 转换原始坐标到显示坐标
            disp_x1 = int(x1 * self._disp_scale)
            disp_y1 = int(y1 * self._disp_scale)
            disp_x2 = int(x2 * self._disp_scale)
            disp_y2 = int(y2 * self._disp_scale)

            # 绘制匹配框
            rect = self.canvas.create_rectangle(disp_x1, disp_y1, disp_x2, disp_y2,
                                              outline="#ff0000", width=2)
            # 绘制标签背景
            label_bg = self.canvas.create_rectangle(disp_x1, disp_y1-20,
                                                   disp_x1+150, disp_y1,
                                                   fill="#000000", outline="#ff0000")
            # 绘制标签文本
            label_text = f"{name} ({conf:.3f})"
            label = self.canvas.create_text(disp_x1+5, disp_y1-10,
                                          text=label_text, fill="#ff0000",
                                          anchor="w", font=("Arial", 9))

            self._match_items.extend([rect, label_bg, label])

    def _clear_match_drawings(self):
        """清除匹配框绘制"""
        for item in self._match_items:
            self.canvas.delete(item)
        self._match_items.clear()

    def _clear_match_results(self):
        """清除匹配结果"""
        self.match_results.clear()
        self.result_list.delete(0, tk.END)
        self._clear_match_drawings()

    def _jump_to_result(self, event):
        """双击结果跳转到对应位置"""
        sel = self.result_list.curselection()
        if not sel:
            return
        index = sel[0]
        if index < len(self.match_results):
            name, conf, (x1, y1, x2, y2) = self.match_results[index]
            # 转换到显示坐标并滚动到中心
            disp_x = int((x1 + x2) / 2 * self._disp_scale)
            disp_y = int((y1 + y2) / 2 * self._disp_scale)
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            self.canvas.xview_moveto(max(0, (disp_x - cw/2) / self._disp_img.width))
            self.canvas.yview_moveto(max(0, (disp_y - ch/2) / self._disp_img.height))
            self._toast(f"已跳转到：{name}")

    # ----------------------- 主入口 -----------------------
    def run(self):
        """运行应用"""
        try:
            self.mainloop()
        except Exception as e:
            messagebox.showerror("运行时错误", f"应用运行出错：\n{e}")


def main():
    """主函数"""
    app = UICropperApp()
    app.run()


if __name__ == "__main__":
    main()
