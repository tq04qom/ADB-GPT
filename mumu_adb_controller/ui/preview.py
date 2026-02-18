import base64, tkinter as tk
from tkinter import ttk
try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

from .constants import PREVIEW_MAX_W, PREVIEW_MAX_H
from .toast import show_toast

def open_coord_preview(app, parent, serial: str, png_bytes: bytes):
    win = tk.Toplevel(parent)
    win.title(f"坐标定位 - {serial}")
    win.resizable(False, False)

    orig_w = orig_h = disp_w = disp_h = 0
    img_obj = None
    current_png_bytes = png_bytes  # 保存当前截图数据用于刷新
    
    def refresh_image():
        """刷新当前画面"""
        nonlocal orig_w, orig_h, disp_w, disp_h, img_obj, current_png_bytes
        
        # 重新截图
        ok, new_png_bytes = app.adb.screencap(serial)
        if not ok or not new_png_bytes:
            show_toast(win, "截图失败，无法刷新", ms=2000)
            return
        
        current_png_bytes = new_png_bytes
        
        # 清除画布
        canvas.delete("all")
        
        # 重新加载图像
        if _HAS_PIL:
            from io import BytesIO
            img = Image.open(BytesIO(current_png_bytes)).convert("RGBA")
            orig_w, orig_h = img.width, img.height
            scale = min(PREVIEW_MAX_W / orig_w, PREVIEW_MAX_H / orig_h, 1.0)
            disp_w, disp_h = max(1, int(orig_w*scale)), max(1, int(orig_h*scale))
            img = img.resize((disp_w, disp_h), Image.LANCZOS)
            img_obj = ImageTk.PhotoImage(img)
        else:
            b64 = base64.b64encode(current_png_bytes).decode("ascii")
            tkimg = tk.PhotoImage(data=b64)
            orig_w, orig_h = tkimg.width(), tkimg.height()
            factor = max(1, int(round(orig_w / PREVIEW_MAX_W)))
            disp_w, disp_h = orig_w // factor, orig_h // factor
            img_obj = tkimg.subsample(factor)
        
        canvas.create_image(0, 0, anchor=tk.NW, image=img_obj)
        canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
        
        # 更新状态
        status_var.set(f"图像尺寸: {orig_w}x{orig_h}, 显示: {disp_w}x{disp_h}")

    def on_click(event):
        """点击获取坐标"""
        if orig_w == 0 or orig_h == 0:
            return
        
        # 获取画布坐标
        canvas_x = canvas.canvasx(event.x)
        canvas_y = canvas.canvasy(event.y)
        
        # 转换为原图坐标
        if _HAS_PIL:
            scale = min(PREVIEW_MAX_W / orig_w, PREVIEW_MAX_H / orig_h, 1.0)
            orig_x = int(canvas_x / scale)
            orig_y = int(canvas_y / scale)
        else:
            factor = max(1, int(round(orig_w / PREVIEW_MAX_W)))
            orig_x = int(canvas_x * factor)
            orig_y = int(canvas_y * factor)
        
        # 确保坐标在有效范围内
        orig_x = max(0, min(orig_x, orig_w - 1))
        orig_y = max(0, min(orig_y, orig_h - 1))
        
        # 更新坐标显示
        coord_var.set(f"坐标: ({orig_x}, {orig_y})")
        
        # 复制到剪贴板
        win.clipboard_clear()
        win.clipboard_append(f"({orig_x}, {orig_y})")
        
        show_toast(win, f"坐标 ({orig_x}, {orig_y}) 已复制到剪贴板", ms=1500)

    # 创建界面
    main_frame = ttk.Frame(win, padding=10)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # 按钮框架
    btn_frame = ttk.Frame(main_frame)
    btn_frame.pack(fill=tk.X, pady=(0, 10))
    
    ttk.Button(btn_frame, text="刷新", command=refresh_image).pack(side=tk.LEFT, padx=(0, 5))
    ttk.Button(btn_frame, text="关闭", command=win.destroy).pack(side=tk.RIGHT)
    
    # 状态显示
    status_frame = ttk.Frame(main_frame)
    status_frame.pack(fill=tk.X, pady=(0, 10))
    
    status_var = tk.StringVar(value="准备就绪")
    coord_var = tk.StringVar(value="坐标: (0, 0)")
    
    ttk.Label(status_frame, textvariable=status_var).pack(side=tk.LEFT)
    ttk.Label(status_frame, textvariable=coord_var).pack(side=tk.RIGHT)
    
    # 画布框架
    canvas_frame = ttk.Frame(main_frame)
    canvas_frame.pack(fill=tk.BOTH, expand=True)
    
    canvas = tk.Canvas(canvas_frame, bg="white", cursor="crosshair")
    
    # 滚动条
    v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
    h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)
    
    canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
    
    # 布局
    canvas.grid(row=0, column=0, sticky="nsew")
    v_scrollbar.grid(row=0, column=1, sticky="ns")
    h_scrollbar.grid(row=1, column=0, sticky="ew")
    
    canvas_frame.grid_rowconfigure(0, weight=1)
    canvas_frame.grid_columnconfigure(0, weight=1)
    
    # 绑定点击事件
    canvas.bind("<Button-1>", on_click)
    
    # 初始化图像
    refresh_image()
