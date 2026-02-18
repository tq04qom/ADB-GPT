# mumu_adb_controller/tools/enhanced_ui_cropper.py
"""
增强版UI截图裁剪工具

功能：
1. 框选模式：截图并保存到指定目录
2. 坐标模式：获取坐标和颜色信息
3. 支持多个子文件夹保存
4. 模板匹配功能
"""

import os
import io
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time

# 路径工具
try:
    from mumu_adb_controller.common.pathutil import res_path
except Exception:
    def _app_base_dir():
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    def res_path(*parts: str):
        return os.path.join(_app_base_dir(), *parts)

# 图像处理
try:
    from PIL import Image, ImageTk, ImageOps, ImageDraw
    _HAS_PIL = True
except Exception:
    print("缺少 Pillow，请先安装：pip install pillow")
    sys.exit(1)

# OpenCV 和 numpy（可选，用于更好的模板匹配）
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

APP_TITLE = "增强版UI截图裁剪工具 v3"
ADB_DEFAULT = res_path("adb", "adb.exe")


class EnhancedUICropper:
    """增强版UI截图裁剪工具"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1000x700")
        
        # 工作模式
        self.mode = tk.StringVar(value="crop")  # crop: 框选模式, coord: 坐标模式
        
        # ADB 相关
        self.adb_path = tk.StringVar(value=ADB_DEFAULT)
        self.device_serial = tk.StringVar()
        
        # 图像相关
        self.current_image = None
        self.display_image = None
        self.original_size = (0, 0)
        self.display_size = (0, 0)
        self.scale_factor = 1.0
        
        # 选择区域
        self.selection_start = None
        self.selection_end = None
        self.selection_rect = None
        
        # 保存路径
        self.save_directory = tk.StringVar(value="pic")
        self.subfolder = tk.StringVar(value="")
        
        # 创建界面
        self._create_ui()
        
        # 绑定事件
        self._bind_events()

        # 初始化界面状态
        self._on_mode_change()
    
    def _create_ui(self):
        """创建用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 控制面板
        self._create_control_panel(main_frame)
        
        # 图像显示区域
        self._create_image_area(main_frame)
        
        # 状态栏
        self._create_status_bar(main_frame)
    
    def _create_control_panel(self, parent):
        """创建控制面板"""
        control_frame = ttk.LabelFrame(parent, text="控制面板", padding=10)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 第一行：模式选择
        mode_frame = ttk.Frame(control_frame)
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(mode_frame, text="工作模式:").pack(side=tk.LEFT)
        ttk.Radiobutton(mode_frame, text="框选模式", variable=self.mode, 
                       value="crop", command=self._on_mode_change).pack(side=tk.LEFT, padx=(10, 5))
        ttk.Radiobutton(mode_frame, text="坐标模式", variable=self.mode, 
                       value="coord", command=self._on_mode_change).pack(side=tk.LEFT, padx=(5, 0))
        
        # 第二行：ADB 设置
        adb_frame = ttk.Frame(control_frame)
        adb_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(adb_frame, text="ADB路径:").pack(side=tk.LEFT)
        ttk.Entry(adb_frame, textvariable=self.adb_path, width=40).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Button(adb_frame, text="浏览", command=self._browse_adb).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(adb_frame, text="设备:").pack(side=tk.LEFT)
        device_combo = ttk.Combobox(adb_frame, textvariable=self.device_serial, width=15)
        device_combo.pack(side=tk.LEFT, padx=(5, 5))
        ttk.Button(adb_frame, text="刷新", command=lambda: self._refresh_devices(device_combo)).pack(side=tk.LEFT)
        
        # 第三行：保存设置（仅框选模式）
        self.save_frame = ttk.Frame(control_frame)
        self.save_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(self.save_frame, text="保存目录:").pack(side=tk.LEFT)
        ttk.Entry(self.save_frame, textvariable=self.save_directory, width=20).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Button(self.save_frame, text="浏览", command=self._browse_save_dir).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(self.save_frame, text="子文件夹:").pack(side=tk.LEFT)
        ttk.Entry(self.save_frame, textvariable=self.subfolder, width=15).pack(side=tk.LEFT, padx=(5, 0))
        
        # 第四行：操作按钮
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="ADB截图", command=self._capture_adb).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="打开本地图片", command=self._open_local).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="刷新", command=self._refresh_image).pack(side=tk.LEFT, padx=(0, 5))
        
        self.save_btn = ttk.Button(button_frame, text="保存选区", command=self._save_selection)
        self.save_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(button_frame, text="模板匹配", command=self._template_match).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="清除选区", command=self._clear_selection).pack(side=tk.LEFT)
        
        # 初始化界面状态将在创建完所有组件后调用
    
    def _create_image_area(self, parent):
        """创建图像显示区域"""
        image_frame = ttk.LabelFrame(parent, text="图像显示", padding=5)
        image_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建滚动画布
        canvas_frame = ttk.Frame(image_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(canvas_frame, bg="white", cursor="crosshair")
        
        # 滚动条
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        
        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # 布局
        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
    
    def _create_status_bar(self, parent):
        """创建状态栏"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.status_var = tk.StringVar(value="就绪")
        self.coord_var = tk.StringVar(value="坐标: (0, 0)")
        self.color_var = tk.StringVar(value="颜色: #000000")
        
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.coord_var).pack(side=tk.LEFT, padx=(20, 0))
        ttk.Label(status_frame, textvariable=self.color_var).pack(side=tk.LEFT, padx=(20, 0))
    
    def _bind_events(self):
        """绑定事件"""
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
    
    def _on_mode_change(self):
        """模式切换处理"""
        mode = self.mode.get()
        if mode == "crop":
            # 框选模式：显示保存设置和保存按钮
            self.save_frame.pack(fill=tk.X, pady=(0, 10))
            self.save_btn.pack(side=tk.LEFT, padx=(0, 5))
            self.canvas.configure(cursor="crosshair")
            self.status_var.set("框选模式：拖拽选择区域进行截图")
        else:
            # 坐标模式：隐藏保存设置和保存按钮
            self.save_frame.pack_forget()
            self.save_btn.pack_forget()
            self.canvas.configure(cursor="tcross")
            self.status_var.set("坐标模式：点击获取坐标和颜色信息")
    
    def _browse_adb(self):
        """浏览ADB路径"""
        filename = filedialog.askopenfilename(
            title="选择ADB可执行文件",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        if filename:
            self.adb_path.set(filename)
    
    def _browse_save_dir(self):
        """浏览保存目录"""
        directory = filedialog.askdirectory(title="选择保存目录")
        if directory:
            self.save_directory.set(directory)
    
    def _refresh_devices(self, combo_widget):
        """刷新设备列表"""
        try:
            result = subprocess.run([self.adb_path.get(), "devices"], 
                                  capture_output=True, text=True, timeout=10)
            devices = []
            for line in result.stdout.split('\n'):
                if '\tdevice' in line:
                    devices.append(line.split('\t')[0])
            
            combo_widget['values'] = devices
            if devices:
                self.device_serial.set(devices[0])
                self.status_var.set(f"找到 {len(devices)} 个设备")
            else:
                self.status_var.set("未找到设备")
        except Exception as e:
            self.status_var.set(f"刷新设备失败: {str(e)}")
    
    def _capture_adb(self):
        """ADB截图"""
        if not self.device_serial.get():
            messagebox.showerror("错误", "请先选择设备")
            return
        
        self.status_var.set("正在截图...")
        self.root.update()
        
        try:
            # 执行ADB截图命令
            cmd = [self.adb_path.get(), "-s", self.device_serial.get(), "exec-out", "screencap", "-p"]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            
            if result.returncode == 0:
                # 加载图像
                image_data = result.stdout
                self._load_image_from_bytes(image_data)
                self.status_var.set("ADB截图成功")
            else:
                self.status_var.set("ADB截图失败")
                
        except Exception as e:
            self.status_var.set(f"截图异常: {str(e)}")
    
    def _open_local(self):
        """打开本地图片"""
        filename = filedialog.askopenfilename(
            title="选择图片文件",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif"),
                ("PNG文件", "*.png"),
                ("JPEG文件", "*.jpg *.jpeg"),
                ("所有文件", "*.*")
            ]
        )
        if filename:
            try:
                with open(filename, 'rb') as f:
                    image_data = f.read()
                self._load_image_from_bytes(image_data)
                self.status_var.set(f"已加载: {os.path.basename(filename)}")
            except Exception as e:
                self.status_var.set(f"加载图片失败: {str(e)}")
    
    def _refresh_image(self):
        """刷新当前图像"""
        if self.device_serial.get():
            self._capture_adb()
        else:
            self.status_var.set("无设备连接，无法刷新")
    
    def _load_image_from_bytes(self, image_data):
        """从字节数据加载图像"""
        try:
            # 使用PIL加载图像
            self.current_image = Image.open(io.BytesIO(image_data)).convert("RGBA")
            self.original_size = self.current_image.size
            
            # 计算显示尺寸
            max_width = 800
            max_height = 600
            scale_w = max_width / self.original_size[0]
            scale_h = max_height / self.original_size[1]
            self.scale_factor = min(scale_w, scale_h, 1.0)
            
            self.display_size = (
                int(self.original_size[0] * self.scale_factor),
                int(self.original_size[1] * self.scale_factor)
            )
            
            # 创建显示图像
            display_img = self.current_image.resize(self.display_size, Image.Resampling.LANCZOS)
            self.display_image = ImageTk.PhotoImage(display_img)
            
            # 更新画布
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self.display_image)
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            
        except Exception as e:
            self.status_var.set(f"加载图像失败: {str(e)}")

    def _on_canvas_click(self, event):
        """画布点击事件"""
        if not self.current_image:
            return

        # 获取实际坐标
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # 转换为原图坐标
        orig_x = int(canvas_x / self.scale_factor)
        orig_y = int(canvas_y / self.scale_factor)

        if self.mode.get() == "coord":
            # 坐标模式：显示坐标和颜色
            self._show_coordinate_info(orig_x, orig_y)
        else:
            # 框选模式：开始选择
            self.selection_start = (canvas_x, canvas_y)
            self.selection_end = None
            if self.selection_rect:
                self.canvas.delete(self.selection_rect)
                self.selection_rect = None

    def _on_canvas_drag(self, event):
        """画布拖拽事件"""
        if not self.current_image or self.mode.get() != "crop":
            return

        if self.selection_start:
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)

            # 更新选择矩形
            if self.selection_rect:
                self.canvas.delete(self.selection_rect)

            self.selection_rect = self.canvas.create_rectangle(
                self.selection_start[0], self.selection_start[1],
                canvas_x, canvas_y,
                outline="red", width=2
            )

    def _on_canvas_release(self, event):
        """画布释放事件"""
        if not self.current_image or self.mode.get() != "crop":
            return

        if self.selection_start:
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)
            self.selection_end = (canvas_x, canvas_y)

            # 显示选择区域信息
            self._show_selection_info()

    def _on_canvas_motion(self, event):
        """画布鼠标移动事件"""
        if not self.current_image:
            return

        # 获取实际坐标
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # 转换为原图坐标
        orig_x = int(canvas_x / self.scale_factor)
        orig_y = int(canvas_y / self.scale_factor)

        # 更新坐标显示
        self.coord_var.set(f"坐标: ({orig_x}, {orig_y})")

        # 如果在坐标模式，实时显示颜色
        if self.mode.get() == "coord":
            self._update_color_info(orig_x, orig_y)

    def _show_coordinate_info(self, x, y):
        """显示坐标信息"""
        try:
            # 获取像素颜色
            if 0 <= x < self.original_size[0] and 0 <= y < self.original_size[1]:
                pixel = self.current_image.getpixel((x, y))
                if len(pixel) >= 3:
                    r, g, b = pixel[:3]
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"

                    self.coord_var.set(f"坐标: ({x}, {y})")
                    self.color_var.set(f"颜色: {hex_color} RGB({r},{g},{b})")

                    # 复制到剪贴板
                    coord_text = f"({x}, {y})"
                    self.root.clipboard_clear()
                    self.root.clipboard_append(coord_text)

                    self.status_var.set(f"坐标 {coord_text} 已复制到剪贴板")

        except Exception as e:
            self.status_var.set(f"获取坐标信息失败: {str(e)}")

    def _update_color_info(self, x, y):
        """更新颜色信息"""
        try:
            if 0 <= x < self.original_size[0] and 0 <= y < self.original_size[1]:
                pixel = self.current_image.getpixel((x, y))
                if len(pixel) >= 3:
                    r, g, b = pixel[:3]
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                    self.color_var.set(f"颜色: {hex_color}")
        except:
            pass

    def _show_selection_info(self):
        """显示选择区域信息"""
        if not self.selection_start or not self.selection_end:
            return

        # 转换为原图坐标
        x1 = int(min(self.selection_start[0], self.selection_end[0]) / self.scale_factor)
        y1 = int(min(self.selection_start[1], self.selection_end[1]) / self.scale_factor)
        x2 = int(max(self.selection_start[0], self.selection_end[0]) / self.scale_factor)
        y2 = int(max(self.selection_start[1], self.selection_end[1]) / self.scale_factor)

        width = x2 - x1
        height = y2 - y1

        self.status_var.set(f"选择区域: ({x1}, {y1}) -> ({x2}, {y2}), 尺寸: {width}x{height}")

    def _save_selection(self):
        """保存选择区域"""
        if not self.current_image or not self.selection_start or not self.selection_end:
            messagebox.showerror("错误", "请先选择区域")
            return

        # 计算裁剪区域
        x1 = int(min(self.selection_start[0], self.selection_end[0]) / self.scale_factor)
        y1 = int(min(self.selection_start[1], self.selection_end[1]) / self.scale_factor)
        x2 = int(max(self.selection_start[0], self.selection_end[0]) / self.scale_factor)
        y2 = int(max(self.selection_start[1], self.selection_end[1]) / self.scale_factor)

        # 裁剪图像
        cropped = self.current_image.crop((x1, y1, x2, y2))

        # 构建保存路径
        save_dir = self.save_directory.get()
        subfolder = self.subfolder.get().strip()

        if subfolder:
            save_dir = os.path.join(save_dir, subfolder)

        # 确保目录存在
        os.makedirs(save_dir, exist_ok=True)

        # 获取文件名
        filename = filedialog.asksaveasfilename(
            title="保存截图",
            initialdir=save_dir,
            defaultextension=".png",
            filetypes=[
                ("PNG文件", "*.png"),
                ("JPEG文件", "*.jpg"),
                ("所有文件", "*.*")
            ]
        )

        if filename:
            try:
                # 转换为RGB模式保存
                if cropped.mode == "RGBA":
                    # 创建白色背景
                    background = Image.new("RGB", cropped.size, (255, 255, 255))
                    background.paste(cropped, mask=cropped.split()[-1])
                    background.save(filename)
                else:
                    cropped.save(filename)

                self.status_var.set(f"已保存: {os.path.basename(filename)}")

            except Exception as e:
                self.status_var.set(f"保存失败: {str(e)}")

    def _clear_selection(self):
        """清除选择区域"""
        if self.selection_rect:
            self.canvas.delete(self.selection_rect)
            self.selection_rect = None

        self.selection_start = None
        self.selection_end = None
        self.status_var.set("已清除选择区域")

    def _template_match(self):
        """模板匹配功能"""
        if not self.current_image:
            messagebox.showerror("错误", "请先加载图像")
            return

        # 选择模板文件
        template_file = filedialog.askopenfilename(
            title="选择模板图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp"),
                ("PNG文件", "*.png"),
                ("所有文件", "*.*")
            ]
        )

        if not template_file:
            return

        try:
            # 加载模板
            template = Image.open(template_file).convert("RGBA")

            # 执行模板匹配
            self._perform_template_matching(template, os.path.basename(template_file))

        except Exception as e:
            self.status_var.set(f"模板匹配失败: {str(e)}")

    def _perform_template_matching(self, template, template_name):
        """执行模板匹配"""
        try:
            if _cv2 is not None and _np is not None:
                # 使用OpenCV进行高精度匹配
                self._opencv_template_match(template, template_name)
            else:
                # 使用PIL进行简单匹配
                self._pil_template_match(template, template_name)

        except Exception as e:
            self.status_var.set(f"模板匹配异常: {str(e)}")

    def _opencv_template_match(self, template, template_name):
        """使用OpenCV进行模板匹配"""
        # 转换为OpenCV格式
        img_array = _np.array(self.current_image.convert("RGB"))
        template_array = _np.array(template.convert("RGB"))

        # 转换为灰度
        img_gray = _cv2.cvtColor(img_array, _cv2.COLOR_RGB2GRAY)
        template_gray = _cv2.cvtColor(template_array, _cv2.COLOR_RGB2GRAY)

        # 模板匹配
        result = _cv2.matchTemplate(img_gray, template_gray, _cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = _cv2.minMaxLoc(result)

        # 显示结果
        if max_val > 0.7:  # 匹配阈值
            x, y = max_loc
            w, h = template.size

            # 在画布上标记匹配位置
            self._mark_match_result(x, y, w, h, max_val, template_name)
        else:
            self.status_var.set(f"未找到匹配的模板 {template_name} (最高置信度: {max_val:.3f})")

    def _pil_template_match(self, template, template_name):
        """使用PIL进行简单模板匹配"""
        # 简化的匹配逻辑
        self.status_var.set(f"正在匹配模板 {template_name}... (使用PIL，精度较低)")
        # 这里可以实现基于PIL的简单匹配算法
        # 暂时显示提示信息
        messagebox.showinfo("提示", "建议安装OpenCV以获得更好的模板匹配效果\npip install opencv-python")

    def _mark_match_result(self, x, y, w, h, confidence, template_name):
        """标记匹配结果"""
        # 转换为显示坐标
        display_x = int(x * self.scale_factor)
        display_y = int(y * self.scale_factor)
        display_w = int(w * self.scale_factor)
        display_h = int(h * self.scale_factor)

        # 在画布上绘制匹配框
        match_rect = self.canvas.create_rectangle(
            display_x, display_y,
            display_x + display_w, display_y + display_h,
            outline="green", width=3
        )

        # 添加标签
        label_text = f"{template_name}\n置信度: {confidence:.3f}\n坐标: ({x}, {y})"
        self.canvas.create_text(
            display_x, display_y - 10,
            text=label_text,
            anchor=tk.SW,
            fill="green",
            font=("Arial", 10, "bold")
        )

        self.status_var.set(f"找到匹配: {template_name} 在 ({x}, {y}), 置信度: {confidence:.3f}")


def main():
    """主函数"""
    app = EnhancedUICropper()
    app.root.mainloop()


if __name__ == "__main__":
    main()
