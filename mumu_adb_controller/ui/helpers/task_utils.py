"""
任务工具类 - 提供任务执行的公共函数
"""
import threading
import tkinter as tk
from typing import Callable, Optional


class TaskUtils:
    """任务执行工具类"""
    
    @staticmethod
    def create_task_wrapper(app, button, stop_event_name: str, task_func: Callable, 
                          reset_func: Optional[Callable] = None):
        """
        创建任务包装器
        
        Args:
            app: 应用实例
            button: 按钮控件
            stop_event_name: 停止事件属性名
            task_func: 任务函数
            reset_func: 重置函数（可选）
        """
        def wrapper():
            try:
                task_func()
            finally:
                def _reset():
                    try:
                        # 若运行时使用了 tk.Button 替换，这里先销毁替换按钮并还原布局
                        swap = getattr(button, '_running_swap_btn', None)
                        if swap is not None:
                            try:
                                mgr = swap.winfo_manager()
                                if mgr == 'grid':
                                    swap.grid_forget()
                                elif mgr == 'pack':
                                    swap.pack_forget()
                            except Exception:
                                pass
                            try:
                                swap.destroy()
                            except Exception:
                                pass
                            try:
                                mgr = getattr(button, '_geom_manager', None)
                                info = getattr(button, '_geom_info', None)
                                if mgr == 'grid' and info:
                                    button.grid(row=info.get('row', 0), column=info.get('column', 0),
                                                columnspan=info.get('columnspan', 1), sticky=info.get('sticky', ''),
                                                padx=info.get('padx', 0), pady=info.get('pady', 0))
                                elif mgr == 'pack' and info:
                                    button.pack(side=info.get('side', 'left'), fill=info.get('fill', None),
                                                expand=info.get('expand', False), padx=info.get('padx', 0), pady=info.get('pady', 0))
                            except Exception:
                                pass
                            try:
                                delattr(button, '_running_swap_btn')
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        button.config(text=button.original_text,
                                      command=button.original_command,
                                      state="normal",
                                      style=(getattr(button, 'original_style', '') or 'TButton'))
                    except Exception:
                        pass
                    try:
                        getattr(app, stop_event_name).clear()
                    except Exception:
                        pass
                    if reset_func:
                        reset_func()
                app.after(0, _reset)
        return wrapper
    
    @staticmethod
    def setup_task_button(button, stop_event_name: str, stop_command: Callable):
        """
        设置任务按钮状态
        
        Args:
            button: 按钮控件
            stop_event_name: 停止事件属性名
            stop_command: 停止命令
        """
        # 保存原始状态
        button.original_text = button.cget("text")
        button.original_command = button.cget("command")
        try:
            button.original_style = button.cget("style")
        except Exception:
            button.original_style = ""

        # 尝试原地换肤：对部分 Windows 主题，ttk 背景会被忽略，这里在运行态用 tk.Button 替换渲染
        # 1) 记录布局信息
        try:
            mgr = button.winfo_manager()
        except Exception:
            mgr = None
        button._geom_manager = mgr
        button._geom_info = None
        parent = button.master
        tk_btn = None
        try:
            if mgr == "grid":
                info = button.grid_info()
                button._geom_info = {
                    "row": int(info.get("row", 0)),
                    "column": int(info.get("column", 0)),
                    "columnspan": int(info.get("columnspan", 1)),
                    "sticky": info.get("sticky", ""),
                    "padx": info.get("padx", 0),
                    "pady": info.get("pady", 0),
                }
                button.grid_forget()
                tk_btn = tk.Button(parent,
                                   text=f"停止{button.original_text}",
                                   command=stop_command,
                                   bg="#0D47A1", fg="white",
                                   activebackground="#0B3D91", activeforeground="white",
                                   relief="raised", bd=1)
                gi = button._geom_info
                tk_btn.grid(row=gi["row"], column=gi["column"], columnspan=gi["columnspan"],
                            sticky=gi["sticky"], padx=gi["padx"], pady=gi["pady"])
            elif mgr == "pack":
                info = button.pack_info()
                button._geom_info = {
                    "side": info.get("side", "left"),
                    "fill": info.get("fill", None),
                    "expand": bool(int(info.get("expand", 0))) if isinstance(info.get("expand", 0), str) else bool(info.get("expand", 0)),
                    "padx": info.get("padx", 0),
                    "pady": info.get("pady", 0),
                }
                button.pack_forget()
                tk_btn = tk.Button(parent,
                                   text=f"停止{button.original_text}",
                                   command=stop_command,
                                   bg="#0D47A1", fg="white",
                                   activebackground="#0B3D91", activeforeground="white",
                                   relief="raised", bd=1)
                pi = button._geom_info
                tk_btn.pack(side=pi["side"], fill=pi["fill"], expand=pi["expand"], padx=pi["padx"], pady=pi["pady"])
        except Exception:
            tk_btn = None
        # 2) 若无法替换，则退化为 TTK 风格切换（可能出现白底白字，但至少可停止）
        if tk_btn is None:
            button.config(text=f"停止{button.original_text}", command=stop_command, style="Running.TButton")
        else:
            button._running_swap_btn = tk_btn

    @staticmethod
    def stop_task(stop_event, button):
        """
        停止任务
        
        Args:
            stop_event: 停止事件
            button: 按钮控件
        """
        try:
            stop_event.set()
        except Exception:
            pass
        try:
            # 同时禁用隐藏的 ttk 按钮和可见的 tk 替换按钮
            button.config(state="disabled")
        except Exception:
            pass
        try:
            swap = getattr(button, "_running_swap_btn", None)
            if swap is not None:
                swap.config(state="disabled")
        except Exception:
            pass

    @staticmethod
    def read_int_param(value: str, default: int) -> int:
        """读取整数参数"""
        try:
            return int(value.strip())
        except Exception:
            return default
    
    @staticmethod
    def read_float_param(value: str, default: float) -> float:
        """读取浮点数参数"""
        try:
            return float(value.strip())
        except Exception:
            return default
    
    @staticmethod
    def create_stop_event() -> threading.Event:
        """创建停止事件"""
        return threading.Event()
