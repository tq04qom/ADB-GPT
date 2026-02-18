import base64, tkinter as tk
from tkinter import ttk
try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

from .constants import THUMB_W, THUMB_H, THUMB_REFRESH_MS

class ThumbGrid(ttk.Frame):
    def __init__(self, master, app, get_devices, on_click_serial):
        super().__init__(master)
        self.app = app
        self.get_devices = get_devices
        self.on_click_serial = on_click_serial
        self._thumb_imgs = {}
        self._timer = None
        self._current_cols = 2  # 初始列数
        self._relayout_job = None
        self._pending_width = None
        self._relayout_force = False

        # 创建主容器
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # 创建画布和滚动条
        self.canvas = tk.Canvas(self.main_frame, highlightthickness=0, bg="#f0f0f0")
        
        # 创建更醒目的滚动条
        self.vbar = ttk.Scrollbar(
            self.main_frame, 
            orient=tk.VERTICAL, 
            command=self.canvas.yview,
            style="Custom.Vertical.TScrollbar"
        )
        
        # 创建内部框架
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", self._on_inner_configure)
        
        # 创建画布窗口
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        
        # 配置滚动条
        self.canvas.configure(yscrollcommand=self.vbar.set)
        
        # 布局：滚动条在右侧，画布占据剩余空间
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 0))
        
        # 绑定窗口大小变化事件
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind("<Configure>", self._on_self_configure)
        
        # 绑定鼠标滚轮事件
        self._bind_mouse_wheel()
        
        # 绑定鼠标拖动事件
        self._bind_mouse_drag()

    def _on_inner_configure(self, event=None):
        """内部框架配置时更新滚动区域"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event=None):
        """画布大小变化时调整内部框架宽度"""
        if event:
            self.canvas.itemconfig(self.canvas_window, width=event.width)
            self._schedule_relayout(event.width)

    def _on_self_configure(self, event=None):
        """自身大小变化时重新计算列数"""
        if event:
            self._schedule_relayout(event.width)

    def _schedule_relayout(self, width=None, *, force=False):
        """延迟执行重排，避免连续 <Configure> 事件造成卡顿"""
        if width is not None:
            self._pending_width = width
        else:
            try:
                self._pending_width = self.winfo_width()
            except Exception:
                self._pending_width = None
        if force:
            self._relayout_force = True
        if self._relayout_job is not None:
            try:
                self.after_cancel(self._relayout_job)
            except Exception:
                pass
        self._relayout_job = self.after(80, self._perform_relayout)

    def _perform_relayout(self):
        """执行实际重排"""
        self._relayout_job = None
        width = self._pending_width
        if not width:
            try:
                width = self.canvas.winfo_width()
            except Exception:
                width = None
        changed = False
        if width and width > 0:
            changed = bool(self._calculate_columns(width))
        if self._relayout_force or changed:
            self._rearrange_grid()
        self._relayout_force = False
        self._pending_width = None

    def _calculate_columns(self, available_width):
        """根据可用宽度计算合适的列数"""
        if available_width <= 0:
            return
            
        # 每个卡片宽度（缩略图宽度 + 内边距 + 外边距）
        card_width = THUMB_W + 16  # 8px padding + 8px margin
        
        # 计算最大列数（至少1列）
        max_cols = max(1, available_width // card_width)
        
        # 如果列数发生变化，更新并重新排列
        if max_cols != self._current_cols:
            self._current_cols = max_cols
            return True
        return False

    def _rearrange_grid(self):
        """重新排列网格布局"""
        if not hasattr(self, 'inner') or not self.inner.winfo_children():
            return
            
        devices = sorted(self.get_devices())
        notes_lookup = self.app.cfg.get("notes", {})
        
        existing_children = list(self.inner.winfo_children())
        card_lookup = {}
        for child in existing_children:
            serial = getattr(child, "_serial", None)
            if serial:
                card_lookup[serial] = child
            child.grid_forget()
        
        # 重新排列
        for idx, s in enumerate(devices):
            r, c = divmod(idx, self._current_cols)
            card = card_lookup.get(s)
            
            if card:
                card.grid(row=r, column=c, padx=4, pady=4, sticky="nw")
            else:
                # 创建新卡片
                card = self._create_card(s, notes_lookup.get(s, ""))
                card.grid(row=r, column=c, padx=4, pady=4, sticky="nw")

    def _create_card(self, serial, note):
        """创建设备卡片"""
        card = ttk.Frame(self.inner, padding=4, relief="groove")
        card._serial = serial
        
        # 创建画布用于显示缩略图
        cv = tk.Canvas(card, width=THUMB_W, height=THUMB_H, highlightthickness=0, bd=0, bg="#111")
        cv.pack()
        
        # 显示标题（备注或序列号）
        title = (note or serial).strip() or serial
        ttk.Label(card, text=title).pack()
        
        # 绑定点击事件
        def on_click(ev=None, s=serial):
            self.on_click_serial(s)
        
        cv.bind("<Button-1>", on_click)
        card.bind("<Button-1>", on_click)
        
        # 绑定滚轮和拖动事件到设备画布
        self._bind_card_scroll_events(cv)
        
        cv._serial = serial
        cv._img_key = f"thumb_{serial}"
        self._thumb_imgs.setdefault(cv._img_key, None)
        
        return card

    def rebuild(self, notes_lookup):
        """重建缩略图网格"""
        # 清除现有内容
        for child in self.inner.winfo_children():
            child.destroy()
        
        devices = sorted(self.get_devices())
        
        # 根据当前宽度计算列数
        available_width = self.canvas.winfo_width()
        if available_width > 0:
            self._calculate_columns(available_width)
        
        # 创建所有卡片
        for idx, s in enumerate(devices):
            r, c = divmod(idx, self._current_cols)
            card = self._create_card(s, notes_lookup.get(s, ""))
            card.grid(row=r, column=c, padx=4, pady=4, sticky="nw")
        
        self.refresh_all_async()
        self._schedule_relayout(force=True)

    def _draw_image(self, png_bytes: bytes):
        if _HAS_PIL:
            from io import BytesIO
            import PIL.Image as Image
            import PIL.ImageTk as ImageTk
            img = Image.open(BytesIO(png_bytes)).convert("RGBA").resize((THUMB_W, THUMB_H), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        else:
            b64 = base64.b64encode(png_bytes).decode("ascii")
            tkimg = tk.PhotoImage(data=b64)
            w = max(1, tkimg.width()); factor = max(1, int(round(w / THUMB_W)))
            return tkimg.subsample(factor, factor)

    def refresh_all_async(self):
        for child in self.inner.winfo_children():
            for w in child.winfo_children():
                if isinstance(w, tk.Canvas) and hasattr(w, "_serial"):
                    serial = w._serial
                    if serial in self.app.workers:
                        self.app.workers[serial].submit(lambda s=serial, cv=w: self._capture_and_draw(s, cv))
        self._schedule_next()

    def refresh_one_async(self, serial: str):
        for child in self.inner.winfo_children():
            for w in child.winfo_children():
                if isinstance(w, tk.Canvas) and getattr(w, "_serial", None) == serial:
                    if serial in self.app.workers:
                        self.app.workers[serial].submit(lambda s=serial, cv=w: self._capture_and_draw(s, cv))
                    return

    def _capture_and_draw(self, serial: str, canvas: tk.Canvas):
        ok, data = self.app.adb.screencap(serial)
        def draw():
            try:
                # 检查画布是否仍然存在
                canvas.winfo_exists()
                canvas.delete("all")
                if ok and data:
                    tkimg = self._draw_image(data)
                    self._thumb_imgs[canvas._img_key] = tkimg
                    x = max(0, (THUMB_W - tkimg.width()) // 2)
                    y = max(0, (THUMB_H - tkimg.height()) // 2)
                    canvas.create_image(x, y, anchor=tk.NW, image=tkimg)
                else:
                    canvas.create_text(THUMB_W//2, THUMB_H//2, text="ERR", fill="#f66")
            except tk.TclError:
                # 画布已被销毁，忽略错误
                pass
        self.app.after(0, draw)

    def _schedule_next(self):
        self.cancel_timer()
        self._timer = self.after(THUMB_REFRESH_MS, self.refresh_all_async)

    def cancel_timer(self):
        if self._timer:
            try: self.after_cancel(self._timer)
            except Exception: pass
            self._timer = None

    def _bind_mouse_wheel(self):
        """绑定鼠标滚轮事件到画布和滚动条"""
        def _on_mouse_wheel(event):
            # 计算滚动方向和速度
            if event.delta:
                # Windows/Mac 滚轮事件
                scroll_amount = -int(event.delta / 120) * 2  # 每滚轮单位滚动2行
            else:
                # Linux 滚轮事件
                scroll_amount = -event.num * 2
            
            # 滚动画布
            self.canvas.yview_scroll(scroll_amount, "units")
        
        # 绑定鼠标滚轮到画布
        self.canvas.bind("<MouseWheel>", _on_mouse_wheel)  # Windows/Mac
        self.canvas.bind("<Button-4>", _on_mouse_wheel)    # Linux 向上滚动
        self.canvas.bind("<Button-5>", _on_mouse_wheel)    # Linux 向下滚动
        
        # 绑定鼠标滚轮到滚动条
        self.vbar.bind("<MouseWheel>", _on_mouse_wheel)
        self.vbar.bind("<Button-4>", _on_mouse_wheel)
        self.vbar.bind("<Button-5>", _on_mouse_wheel)
        
        # 绑定鼠标滚轮到内部框架（当鼠标在设备卡片上时）
        self.inner.bind("<MouseWheel>", _on_mouse_wheel)
        self.inner.bind("<Button-4>", _on_mouse_wheel)
        self.inner.bind("<Button-5>", _on_mouse_wheel)

    def _bind_mouse_drag(self):
        """绑定鼠标拖动事件到画布和内部框架"""
        # 拖动状态变量
        self._drag_start_y = 0
        self._drag_scroll_start = 0
        self._is_dragging = False
        
        def _on_drag_start(event):
            """开始拖动"""
            self._drag_start_y = event.y
            self._drag_scroll_start = self.canvas.yview()[0]  # 获取当前滚动位置
            self._is_dragging = True
            # 更改鼠标光标为拖动样式
            self.canvas.config(cursor="hand2")
        
        def _on_drag_move(event):
            """拖动过程中"""
            if self._is_dragging:
                # 计算拖动距离
                delta_y = event.y - self._drag_start_y
                
                # 计算新的滚动位置
                scroll_region = self.canvas.bbox("all")
                if scroll_region:
                    canvas_height = self.canvas.winfo_height()
                    content_height = scroll_region[3] - scroll_region[1]
                    
                    if content_height > canvas_height:
                        # 计算滚动比例
                        scroll_delta = delta_y / content_height
                        new_scroll = self._drag_scroll_start - scroll_delta
                        
                        # 限制滚动范围在0到1之间
                        new_scroll = max(0, min(1, new_scroll))
                        
                        # 应用滚动
                        self.canvas.yview_moveto(new_scroll)
        
        def _on_drag_end(event):
            """结束拖动"""
            self._is_dragging = False
            # 恢复默认鼠标光标
            self.canvas.config(cursor="")
        
        # 绑定拖动事件到画布
        self.canvas.bind("<ButtonPress-1>", _on_drag_start)
        self.canvas.bind("<B1-Motion>", _on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", _on_drag_end)
        
        # 绑定拖动事件到内部框架
        self.inner.bind("<ButtonPress-1>", _on_drag_start)
        self.inner.bind("<B1-Motion>", _on_drag_move)
        self.inner.bind("<ButtonRelease-1>", _on_drag_end)

    def _bind_card_scroll_events(self, card_canvas):
        """为设备卡片画布绑定滚轮和拖动事件"""
        # 绑定滚轮事件
        def _on_card_mouse_wheel(event):
            # 计算滚动方向和速度
            if event.delta:
                # Windows/Mac 滚轮事件
                scroll_amount = -int(event.delta / 120) * 2  # 每滚轮单位滚动2行
            else:
                # Linux 滚轮事件
                scroll_amount = -event.num * 2
            
            # 滚动画布
            self.canvas.yview_scroll(scroll_amount, "units")
        
        card_canvas.bind("<MouseWheel>", _on_card_mouse_wheel)  # Windows/Mac
        card_canvas.bind("<Button-4>", _on_card_mouse_wheel)    # Linux 向上滚动
        card_canvas.bind("<Button-5>", _on_card_mouse_wheel)    # Linux 向下滚动
        
        # 拖动状态变量
        card_canvas._drag_start_y = 0
        card_canvas._drag_scroll_start = 0
        card_canvas._is_dragging = False
        
        def _on_card_drag_start(event):
            """开始拖动"""
            # 记录初始位置
            card_canvas._drag_start_y = event.y_root
            card_canvas._drag_scroll_start = self.canvas.yview()[0]
            card_canvas._is_dragging = False  # 初始状态不是拖动
        
        def _on_card_drag_move(event):
            """拖动过程中"""
            if not card_canvas._is_dragging:
                # 检查是否达到拖动阈值（移动超过5像素才认为是拖动）
                if abs(event.y_root - card_canvas._drag_start_y) > 5:
                    card_canvas._is_dragging = True
                    # 更改鼠标光标为拖动样式
                    self.canvas.config(cursor="hand2")
            
            if card_canvas._is_dragging:
                # 计算拖动距离（使用屏幕坐标）
                delta_y = event.y_root - card_canvas._drag_start_y
                
                # 计算新的滚动位置
                scroll_region = self.canvas.bbox("all")
                if scroll_region:
                    canvas_height = self.canvas.winfo_height()
                    content_height = scroll_region[3] - scroll_region[1]
                    
                    if content_height > canvas_height:
                        # 计算滚动比例
                        scroll_delta = delta_y / content_height
                        new_scroll = card_canvas._drag_scroll_start - scroll_delta
                        
                        # 限制滚动范围在0到1之间
                        new_scroll = max(0, min(1, new_scroll))
                        
                        # 应用滚动
                        self.canvas.yview_moveto(new_scroll)
        
        def _on_card_drag_end(event):
            """结束拖动"""
            if card_canvas._is_dragging:
                # 如果是拖动操作，恢复默认鼠标光标
                self.canvas.config(cursor="")
            else:
                # 如果不是拖动操作，触发点击事件
                serial = getattr(card_canvas, "_serial", None)
                if serial:
                    self.on_click_serial(serial)
            
            # 重置拖动状态
            card_canvas._is_dragging = False
        
        card_canvas.bind("<ButtonPress-1>", _on_card_drag_start)
        card_canvas.bind("<B1-Motion>", _on_card_drag_move)
        card_canvas.bind("<ButtonRelease-1>", _on_card_drag_end)
