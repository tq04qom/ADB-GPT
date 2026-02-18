# mumu_adb_controller/ui/common_patterns.py
"""
通用UI模式和工具函数

提取常见的UI创建模式，减少代码重复。
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Tuple, Optional, Callable, Any


class UIPatterns:
    """通用UI模式类"""
    
    @staticmethod
    def create_labeled_entry(parent: tk.Widget, label_text: str, 
                           textvariable: tk.StringVar = None, 
                           width: int = 10, **kwargs) -> Tuple[ttk.Label, ttk.Entry]:
        """创建带标签的输入框"""
        label = ttk.Label(parent, text=label_text)
        
        entry_kwargs = {'width': width}
        if textvariable:
            entry_kwargs['textvariable'] = textvariable
        entry_kwargs.update(kwargs)
        
        entry = ttk.Entry(parent, **entry_kwargs)
        
        return label, entry
    
    @staticmethod
    def create_parameter_grid(parent: tk.Widget, 
                            parameters: List[Tuple[str, tk.StringVar, int]],
                            columns: int = 2) -> ttk.Frame:
        """创建参数输入网格"""
        frame = ttk.Frame(parent)
        
        for i, (label_text, var, width) in enumerate(parameters):
            row = i // columns
            col = (i % columns) * 2
            
            label = ttk.Label(frame, text=label_text)
            label.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=2)
            
            entry = ttk.Entry(frame, textvariable=var, width=width)
            entry.grid(row=row, column=col+1, sticky="w", padx=(0, 16), pady=2)
        
        return frame
    
    @staticmethod
    def create_radio_group(parent: tk.Widget, 
                          variable: tk.StringVar,
                          options: List[Tuple[str, str]],
                          command: Callable = None,
                          orientation: str = "horizontal") -> ttk.Frame:
        """创建单选按钮组"""
        frame = ttk.Frame(parent)
        
        for i, (text, value) in enumerate(options):
            radio = ttk.Radiobutton(
                frame,
                text=text,
                variable=variable,
                value=value,
                command=command
            )
            
            if orientation == "horizontal":
                radio.pack(side=tk.LEFT, padx=(0, 8))
            else:
                radio.pack(anchor="w", pady=2)
        
        return frame
    
    @staticmethod
    def create_button_row(parent: tk.Widget, 
                         buttons: List[Dict[str, Any]],
                         spacing: int = 8) -> ttk.Frame:
        """创建按钮行"""
        frame = ttk.Frame(parent)
        
        for button_config in buttons:
            text = button_config.get('text', 'Button')
            command = button_config.get('command')
            style = button_config.get('style', 'TButton')
            
            btn = ttk.Button(frame, text=text, command=command, style=style)
            btn.pack(side=tk.LEFT, padx=(0, spacing))
        
        return frame
    
    @staticmethod
    def create_scrollable_text(parent: tk.Widget, 
                              height: int = 10,
                              width: int = 50,
                              **kwargs) -> Tuple[ttk.Frame, tk.Text, ttk.Scrollbar]:
        """创建带滚动条的文本框"""
        container = ttk.Frame(parent)
        
        # 创建文本框
        text_kwargs = {
            'height': height,
            'width': width,
            'wrap': tk.WORD,
            'state': tk.DISABLED
        }
        text_kwargs.update(kwargs)
        
        text_widget = tk.Text(container, **text_kwargs)
        
        # 创建滚动条
        scrollbar = ttk.Scrollbar(container, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        # 布局
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        return container, text_widget, scrollbar
    
    @staticmethod
    def create_progress_section(parent: tk.Widget, 
                               title: str = "进度") -> Tuple[ttk.LabelFrame, ttk.Progressbar, ttk.Label]:
        """创建进度显示区域"""
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        
        # 进度条
        progress = ttk.Progressbar(frame, mode='indeterminate')
        progress.pack(fill=tk.X, pady=(0, 8))
        
        # 状态标签
        status_label = ttk.Label(frame, text="就绪")
        status_label.pack()
        
        return frame, progress, status_label
    
    @staticmethod
    def create_info_card(parent: tk.Widget, 
                        title: str,
                        info_items: List[Tuple[str, str]]) -> ttk.LabelFrame:
        """创建信息卡片"""
        card = ttk.LabelFrame(parent, text=title, padding=12, style="Card.TLabelframe")
        
        for label_text, value_text in info_items:
            row_frame = ttk.Frame(card)
            row_frame.pack(fill=tk.X, pady=2)
            
            label = ttk.Label(row_frame, text=f"{label_text}:")
            label.pack(side=tk.LEFT)
            
            value = ttk.Label(row_frame, text=value_text, style="Subtle.TLabel")
            value.pack(side=tk.RIGHT)
        
        return card
    
    @staticmethod
    def create_collapsible_section(parent: tk.Widget, 
                                  title: str,
                                  content_creator: Callable[[tk.Widget], None]) -> ttk.Frame:
        """创建可折叠区域"""
        main_frame = ttk.Frame(parent)
        
        # 标题栏（可点击）
        header_frame = ttk.Frame(main_frame, style="Card.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 4))
        
        # 展开/折叠状态
        expanded = tk.BooleanVar(value=True)
        
        # 标题标签
        title_label = ttk.Label(header_frame, text=f"▼ {title}", cursor="hand2")
        title_label.pack(side=tk.LEFT, padx=8, pady=4)
        
        # 内容区域
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建内容
        content_creator(content_frame)
        
        def toggle_section():
            if expanded.get():
                content_frame.pack_forget()
                title_label.configure(text=f"▶ {title}")
                expanded.set(False)
            else:
                content_frame.pack(fill=tk.BOTH, expand=True)
                title_label.configure(text=f"▼ {title}")
                expanded.set(True)
        
        title_label.bind("<Button-1>", lambda e: toggle_section())
        
        return main_frame


class TaskUIHelper:
    """任务相关UI辅助类"""
    
    @staticmethod
    def create_task_control_panel(parent: tk.Widget,
                                 task_name: str,
                                 start_command: Callable,
                                 stop_command: Callable,
                                 parameters: List[Tuple[str, tk.StringVar, int]] = None) -> ttk.LabelFrame:
        """创建任务控制面板"""
        panel = ttk.LabelFrame(parent, text=task_name, padding=12, style="Card.TLabelframe")
        
        # 参数区域
        if parameters:
            param_frame = UIPatterns.create_parameter_grid(panel, parameters)
            param_frame.pack(fill=tk.X, pady=(0, 12))
        
        # 控制按钮
        button_configs = [
            {'text': '开始', 'command': start_command, 'style': 'Accent.TButton'},
            {'text': '停止', 'command': stop_command, 'style': 'TButton'}
        ]
        
        button_frame = UIPatterns.create_button_row(panel, button_configs)
        button_frame.pack()
        
        return panel
    
    @staticmethod
    def create_device_info_panel(parent: tk.Widget,
                               serial: str,
                               status_var: tk.StringVar) -> ttk.Frame:
        """创建设备信息面板"""
        panel = ttk.Frame(parent)
        
        # 设备标题
        title_frame = ttk.Frame(panel)
        title_frame.pack(fill=tk.X, pady=(0, 8))
        
        title_label = ttk.Label(title_frame, text=f"设备: {serial}", font=('Segoe UI', 12, 'bold'))
        title_label.pack(side=tk.LEFT)
        
        status_label = ttk.Label(title_frame, textvariable=status_var, style="Subtle.TLabel")
        status_label.pack(side=tk.RIGHT)
        
        return panel


class LogHelper:
    """日志相关辅助类"""
    
    @staticmethod
    def create_enhanced_log_area(parent: tk.Widget, 
                               title: str = "日志",
                               height: int = 12) -> Tuple[ttk.LabelFrame, tk.Text]:
        """创建增强的日志区域"""
        log_frame = ttk.LabelFrame(parent, text=title, padding=8, style="Card.TLabelframe")
        
        # 创建带滚动条的文本区域
        container, text_widget, scrollbar = UIPatterns.create_scrollable_text(
            log_frame, 
            height=height,
            bg='#f8f9fa',
            fg='#212529',
            font=('Consolas', 9)
        )
        container.pack(fill=tk.BOTH, expand=True)
        
        # 添加右键菜单
        context_menu = tk.Menu(text_widget, tearoff=0)
        context_menu.add_command(label="复制", command=lambda: LogHelper._copy_selection(text_widget))
        context_menu.add_command(label="全选", command=lambda: LogHelper._select_all(text_widget))
        context_menu.add_separator()
        context_menu.add_command(label="清空", command=lambda: LogHelper._clear_log(text_widget))
        
        def show_context_menu(event):
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()
        
        text_widget.bind("<Button-3>", show_context_menu)
        
        return log_frame, text_widget
    
    @staticmethod
    def _copy_selection(text_widget: tk.Text):
        """复制选中文本"""
        try:
            text_widget.clipboard_clear()
            text_widget.clipboard_append(text_widget.selection_get())
        except tk.TclError:
            pass
    
    @staticmethod
    def _select_all(text_widget: tk.Text):
        """全选文本"""
        text_widget.tag_add(tk.SEL, "1.0", tk.END)
        text_widget.mark_set(tk.INSERT, "1.0")
        text_widget.see(tk.INSERT)
    
    @staticmethod
    def _clear_log(text_widget: tk.Text):
        """清空日志"""
        text_widget.configure(state=tk.NORMAL)
        text_widget.delete(1.0, tk.END)
        text_widget.configure(state=tk.DISABLED)
    
    @staticmethod
    def append_log(text_widget: tk.Text, message: str, level: str = "INFO"):
        """添加日志消息"""
        try:
            text_widget.configure(state=tk.NORMAL)
            
            # 根据级别设置颜色
            color_map = {
                "INFO": "#212529",
                "SUCCESS": "#28a745", 
                "WARNING": "#ffc107",
                "ERROR": "#dc3545",
                "DEBUG": "#6c757d"
            }
            
            color = color_map.get(level, "#212529")
            
            # 插入消息
            text_widget.insert(tk.END, f"{message}\n")
            
            # 设置颜色（如果支持）
            if level != "INFO":
                start_line = text_widget.index(tk.END + "-2l linestart")
                end_line = text_widget.index(tk.END + "-1l lineend")
                text_widget.tag_add(level, start_line, end_line)
                text_widget.tag_config(level, foreground=color)
            
            text_widget.configure(state=tk.DISABLED)
            text_widget.see(tk.END)
            
        except Exception as e:
            print(f"Log append error: {e}")


# 全局实例
ui_patterns = UIPatterns()
task_ui_helper = TaskUIHelper()
log_helper = LogHelper()
