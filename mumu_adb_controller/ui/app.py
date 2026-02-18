import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Dict, List
import threading
import concurrent.futures
from .theme import apply_theme
from ..common.config import AppConfig
from ..common.logger import Logger
from ..common.worker import DeviceWorker
from ..core.adb import AdbClient
from .constants import LEFT_DEFAULT_WIDTH
from .layout import restore_paned_width, save_paned_width
from .thumb_grid import ThumbGrid
from .device_tab import DeviceTab
from .helpers.task_utils import TaskUtils
from .tasks.offline_monitor import run_offline_monitor


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("无尽辅助羽柔子开发威力加强版")
        self.geometry("1180x780")
        self.minsize(1080, 700)

        # 配置
        self.config_mgr = AppConfig(app_name="MuMuADBController")
        self.cfg = self.config_mgr.load()

        # 日志与 ADB
        self.logger = Logger()
        self.logger.set_sink(self._enqueue_main_log)
        self.adb = AdbClient(adb_path=self.cfg.get("adb_path"), logger=self.logger)

        self.workers: Dict[str, DeviceWorker] = {}
        self.device_tabs: Dict[str, DeviceTab] = {}

        # 全局任务注册与互斥控制
        self.running_tasks = {}       # key -> {stop_event, resume, button}
        self._suspended_for_offmon = []  # 暂停的任务（resume 回调列表）
        self._offmon_round_active = False
        # 全局暂停
        self.pause_event = threading.Event()

        # 构建 UI
        self._build_ui()

        # 恢复窗口与 ADB 路径
        if self.cfg.get("geometry"):
            self.geometry(self.cfg["geometry"])
        if self.cfg.get("adb_path"):
            self.adb_path_var.set(self.cfg["adb_path"])

        # 初次刷新
        self.refresh_devices()

        # 恢复分栏宽度（解决启动重置）
        # 恢复分栏宽度（self.split 在 _build_ui 后段才创建；这里延迟到 idle 再恢复，避免属性未就绪）
        def _restore_split():
            try:
                if getattr(self, "split", None) is not None:
                    restore_paned_width(
                        self,
                        self.split,
                        0,
                        int(self.cfg.get("layout", {}).get("split_left", LEFT_DEFAULT_WIDTH)),
                    )
            except Exception:
                pass
        try:
            self.after(0, _restore_split)
        except Exception:
            _restore_split()

        # 延迟到 UI 元素就绪后再执行标签重建与视图模式应用
        def _post_ui_tasks():
            if hasattr(self, "nb_content") and hasattr(self, "list_frame") and hasattr(self, "thumb_frame"):
                try:
                    self._rebuild_tabs_from_config()
                except Exception:
                    pass
                try:
                    self._apply_view_mode(initial=True)
                except Exception:
                    pass
            else:
                # 若尚未就绪，稍后重试
                try:
                    self.after(50, _post_ui_tasks)
                except Exception:
                    pass
        try:
            self.after(0, _post_ui_tasks)
        except Exception:
            _post_ui_tasks()

        # 标签切换：缩略图模式下刷新对应缩略图（多行标签：上下两行都绑定）
        # 绑定在 _build_ui 中设置 self.nb1/self.nb2

    # ----------------- UI -----------------
    def _build_ui(self):
        apply_theme(self)  # ★ 一行启用主题
        # 顶栏
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="ADB 路径：").pack(side=tk.LEFT)
        self.adb_path_var = tk.StringVar(value=os.environ.get("ADB_PATH", ""))
        ttk.Entry(top, textvariable=self.adb_path_var, width=40).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="浏览…", style="Small.TButton", command=self.browse_adb).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="应用并保存", style="Small.TButton", command=self.apply_adb_path).pack(side=tk.LEFT, padx=4)
        # 全局运行速度与全局操作模式
        ttk.Label(top, text="运行速度").pack(side=tk.LEFT, padx=(16, 4))
        self.speed_factor_var = tk.StringVar(value=str(self.cfg.get("speed_factor", "1.0")))
        ttk.Entry(top, textvariable=self.speed_factor_var, width=5).pack(side=tk.LEFT)
        ttk.Button(top, text="应用速度", command=self.apply_speed_factor).pack(side=tk.LEFT, padx=4)
        self.multi_mode_var = tk.BooleanVar(value=bool(self.cfg.get("global_multi", False)))
        ttk.Checkbutton(top, text="全局操作模式", variable=self.multi_mode_var, command=self.apply_multi_mode).pack(side=tk.LEFT, padx=(16, 6))
        # 全局暂停/继续
        self.pause_btn = ttk.Button(top, text="暂停", style="Small.TButton", command=self.toggle_pause)
        self.pause_btn.pack(side=tk.LEFT, padx=(8, 6))
        # 紧急一键停止（醒目）
        self.emergency_stop_btn = ttk.Button(top, text="停止运行", style="Small.Accent.TButton", command=self.force_stop_all_safe)
        self.emergency_stop_btn.pack(side=tk.LEFT, padx=(0, 0))

        bar = ttk.Frame(self, padding=8, style="Card.TFrame")
        bar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(bar, text="刷新设备", style="Small.Accent.TButton", command=self.refresh_devices).pack(side=tk.LEFT)
        ttk.Button(bar, text="自动连接MuMu", style="Small.TButton", command=self.auto_connect_mumu).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="排序标签", style="Small.TButton", command=self.sort_tabs_toggle).pack(side=tk.LEFT, padx=(8, 4))
        self.tab_list_btn = ttk.Button(bar, text="标签列表", style="Small.TButton", command=self.show_tab_list_menu)
        self.tab_list_btn.pack(side=tk.LEFT, padx=(4, 8))
        # 折叠/展开 设备区
        self.left_collapsed = False
        self.collapse_btn = ttk.Button(bar, text="折叠设备区", style="Small.TButton", command=self._toggle_left_pane)
        self.collapse_btn.pack(side=tk.LEFT, padx=(0, 12))

        # 右侧：全局掉线监控（间隔+按钮）
        def _offmon_log(msg: str):
            try:
                self.logger.info(msg)
                self._append_timeline(msg)
            except Exception:
                print(msg)
        def _offmon_toast(msg: str):
            # 仅显示轻提示，不再重复写入日志，避免一条信息重复两次
            try:
                from .toast import show_toast
                show_toast(root=self, text=str(msg), ms=2000)
            except Exception:
                pass
        def _offmon_should_stop():
            ev = getattr(self, "_offline_mon_stop_ev", None)
            return bool(ev and ev.is_set())
        def _offmon_task():
            mins = 15
            try:
                mins = int((self.offmon_interval_var.get() or "15").strip())
            except Exception:
                mins = 15
            run_offline_monitor(self, mins, _offmon_should_stop, _offmon_toast, _offmon_log, threshold=None, verbose=False)
        def _offmon_stop():
            TaskUtils.stop_task(getattr(self, "_offline_mon_stop_ev", None), self.offmon_btn)
            try:
                self.unregister_task("global:offline_monitor")
            except Exception:
                pass
        def _offmon_start():
            import threading as _threading
            self._offline_mon_stop_ev = TaskUtils.create_stop_event()
            TaskUtils.setup_task_button(self.offmon_btn, "_offline_mon_stop_ev", _offmon_stop)
            # 注册为全局任务（最高优先级）
            try:
                self.register_task("global:offline_monitor", self._offline_mon_stop_ev, resume_cb=None, button=self.offmon_btn)
            except Exception:
                pass
            wrapper = TaskUtils.create_task_wrapper(self, self.offmon_btn, "_offline_mon_stop_ev", _offmon_task)
            t = _threading.Thread(target=wrapper, daemon=True)
            t.start()
        spacer = ttk.Frame(bar)
        spacer.pack(side=tk.RIGHT)
        ttk.Label(bar, text="监控间隔(分)").pack(side=tk.RIGHT, padx=(8, 4))
        self.offmon_interval_var = tk.StringVar(value=str(self.cfg.get("offmon_interval_min", 15)))
        ttk.Entry(bar, textvariable=self.offmon_interval_var, width=5).pack(side=tk.RIGHT)
        self.offmon_btn = ttk.Button(bar, text="小小号掉线监控", style="Small.Accent.TButton", command=_offmon_start)
        self.offmon_btn.pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Label(bar, text="连接 IP:端口").pack(side=tk.LEFT, padx=(16, 4))
        self.ip_port_var = tk.StringVar(value="127.0.0.1:7555")
        ttk.Entry(bar, textvariable=self.ip_port_var, width=22).pack(side=tk.LEFT)
        ttk.Button(bar, text="连接", command=self.connect_ip_port).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="断开所选", command=self.disconnect_selected).pack(side=tk.LEFT, padx=4)


        self.split = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.split.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # 左：设备页（模式切换 + 列表/缩略图）
        left = ttk.Frame(self.split, padding=4)
        self.left_pane = left
        self.split.add(left, weight=1)
        try:
            self.split.paneconfigure(left, minsize=180)
        except Exception:
            pass

        # 右：标签页
        right = ttk.Frame(self.split, padding=4)
        self.right_pane = right
        self.split.add(right, weight=5)
        try:
            self.split.paneconfigure(right, minsize=700)
        except Exception:
            pass

        # 左上：模式切换
        mode_bar = ttk.Frame(left)
        mode_bar.pack(fill=tk.X)
        ttk.Label(mode_bar, text="设备页显示：").pack(side=tk.LEFT)
        self.view_mode_var = tk.StringVar(value=self.cfg.get("device_view_mode", "list"))
        ttk.Radiobutton(
            mode_bar, text="列表", variable=self.view_mode_var, value="list", command=self._apply_view_mode
        ).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Radiobutton(
            mode_bar, text="缩略图", variable=self.view_mode_var, value="thumb", command=self._apply_view_mode
        ).pack(side=tk.LEFT)

        # ---- 列表模式控件 ----
        self.list_frame = ttk.Frame(left)
        ttk.Label(self.list_frame, text="设备（多选）：").pack(anchor=tk.W)
        self.devices_list = tk.Listbox(self.list_frame, selectmode=tk.EXTENDED)
        self.devices_list.pack(fill=tk.BOTH, expand=True)
        self.devices_list.bind("<<ListboxSelect>>", self.on_device_select)

        note_frame = ttk.LabelFrame(self.list_frame, text="设备备注（保存后生成/更新设备标签页）")
        note_frame.pack(fill=tk.X, pady=6)
        self.note_text = tk.Text(note_frame, height=3, wrap="word")
        self.note_text.pack(fill=tk.X, padx=4, pady=4)
        btn_row = ttk.Frame(note_frame)
        btn_row.pack(fill=tk.X, padx=4, pady=(0, 6))
        ttk.Button(btn_row, text="保存备注并生成标签", command=self.save_note_for_selected).pack(side=tk.RIGHT)

        # 左侧不再承载日志；日志区域移动到右侧设备标签下方（见右侧布局）

        # ---- 缩略图模式控件 ----
        self.thumb_frame = ttk.Frame(left)

        # 缩略图网格
        self.thumb_grid = ThumbGrid(
            self.thumb_frame,
            self,
            get_devices=lambda: list(self.workers.keys()),
            on_click_serial=lambda s: (
                self._create_or_update_tab(s),
                self._select_tab(s),
                self.thumb_grid.refresh_one_async(s),
            ),
        )
        self.thumb_grid.pack(fill=tk.BOTH, expand=True)

        # 缩略图模式下的备注输入框
        thumb_note_frame = ttk.LabelFrame(self.thumb_frame, text="设备备注（保存后生成/更新设备标签页）")
        thumb_note_frame.pack(fill=tk.X, pady=6)
        self.thumb_note_text = tk.Text(thumb_note_frame, height=3, wrap="word")
        self.thumb_note_text.pack(fill=tk.X, padx=4, pady=4)
        thumb_btn_row = ttk.Frame(thumb_note_frame)
        thumb_btn_row.pack(fill=tk.X, padx=4, pady=(0, 6))
        ttk.Button(thumb_btn_row, text="保存备注并生成标签", command=self.save_note_for_selected).pack(side=tk.RIGHT)

        # 右：自绘两行页签头 + 单一内容区（隐藏原生页签）
        tabs_wrap = ttk.Frame(right)
        tabs_wrap.pack(fill=tk.BOTH, expand=True)
        header = ttk.Frame(tabs_wrap)

        header.pack(fill=tk.X, expand=False)
        # 两行容器（不使用滚动按钮）
        self.tab_header_row1 = ttk.Frame(header)
        self.tab_header_row1.pack(fill=tk.X, expand=False)
        self.tab_header_row2 = ttk.Frame(header)
        self.tab_header_row2.pack(fill=tk.X, expand=False)
        # 内容区
        self.nb_content = ttk.Notebook(tabs_wrap, style="Hidden.TNotebook")
        self.nb_content.pack(fill=tk.BOTH, expand=True)
        self.nb_content.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.tab_buttons: Dict[str, ttk.Button] = {}
        self.tab_order: list[str] = list(self.cfg.get("devices", []))
        # 右侧下方：日志区域（三标签：主日志 / 设备日志 / 时间流）
        lognb = ttk.Notebook(tabs_wrap)
        lognb.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.log_nb = lognb
        # 主日志
        main_tab = ttk.Frame(lognb)
        self.main_log = tk.Text(main_tab, wrap="word", height=10)
        self.main_log.pack(fill=tk.BOTH, expand=True)
        #  UI 
        try:
            buf = getattr(self, "_pre_ui_logs", None)
            if buf:
                for m in buf:
                    self.main_log.insert("end", f"{m}\n")
                self.main_log.see("end")
                try:
                    del self._pre_ui_logs
                except Exception:
                    pass
        except Exception:
            pass
        lognb.add(main_tab, text="主日志")
        # 设备日志镜像
        dev_tab = ttk.Frame(lognb)
        self.dev_log_view = tk.Text(dev_tab, wrap="word", height=10)
        self.dev_log_view.pack(fill=tk.BOTH, expand=True)
        lognb.add(dev_tab, text="设备日志")
        # 时间流全局日志
        timeline_tab = ttk.Frame(lognb)
        self.timeline_log = tk.Text(timeline_tab, wrap="word", height=10)
        self.timeline_log.pack(fill=tk.BOTH, expand=True)
        lognb.add(timeline_tab, text="时间流")

    def _select_log_tab(self, which: str):
        try:
            if not hasattr(self, "log_nb"):
                return
            if which == "main":
                self.log_nb.select(0)
            elif which == "device":
                self.log_nb.select(1)
            elif which == "timeline":
                self.log_nb.select(2)
        except Exception:
            pass
    def _rebuild_tab_header(self):
        """重建两行页签头（支持滚动与固定宽度）。"""
        try:
            for w in list(self.tab_header_row1.winfo_children()):
                w.destroy()
            for w in list(self.tab_header_row2.winfo_children()):
                w.destroy()
        except Exception:
            pass
        self.tab_buttons.clear()
        order = self.cfg.get("devices", list(self.device_tabs.keys()))
        def _short(txt: str) -> str:
            t = (txt or "").strip()
            return t[:5] if len(t) > 5 else t
        for i, s in enumerate(order):
            note = self.cfg.get("notes", {}).get(s, "")
            title = (note.strip() or s)

            disp = _short(title)
            row = self.tab_header_row1 if i < 13 else self.tab_header_row2
            btn = ttk.Button(row, text=disp, style="Small.TButton", command=lambda ss=s: self._select_tab(ss))
            btn.pack(side=tk.LEFT, padx=(2, 2), pady=(1, 1))
            self.tab_buttons[s] = btn
        self._update_header_selection()
        self._update_tab_rows_visibility()

    def _update_header_selection(self):
        sel = self._current_tab_serial()
        for s, btn in self.tab_buttons.items():
            try:
                btn.configure(style=("Small.Accent.TButton" if s == sel else "Small.TButton"))
            except Exception:
                pass

    def _current_tab_serial(self) -> str | None:
        try:
            tid = self.nb_content.select()
            for s, tab in self.device_tabs.items():
                if str(tab) == tid:
                    return s
        except Exception:
            pass
        return None


    def _sync_dev_log_view(self):
        """将当前选中设备的日志同步到左侧“设备日志”页。"""
        try:
            if not hasattr(self, "dev_log_view"):
                return
            # 找出当前选中的设备 tab（来自内容区 nb_content）
            curr = self.nb_content.select()
            sel_serial = None
            for s, tab in self.device_tabs.items():
                if str(tab) == curr:
                    sel_serial = s
                    break
            self.current_log_serial = sel_serial
            self.dev_log_view.delete("1.0", "end")
            if sel_serial:

                tab = self.device_tabs.get(sel_serial)
                if tab and hasattr(tab, "log_text"):
                    content = tab.log_text.get("1.0", "end-1c")
                    self.dev_log_view.insert("end", content)
                    self.dev_log_view.see("end")
        except Exception:
            pass



        # 关闭事件
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----------------- 日志（线程安全） -----------------
    def _enqueue_main_log(self, msg: str):
        self.after(0, self._append_main_log, msg)
    def _append_timeline(self, msg: str):
        try:
            if hasattr(self, "timeline_log"):
                self.timeline_log.insert("end", f"{msg}\n")
                self.timeline_log.see("end")
        except Exception:
            pass


    def _append_main_log(self, msg: str):
        # 仅写入主日志；若 UI 尚未构建完成，则暂存缓冲
        try:
            if not hasattr(self, "main_log"):
                self._pre_ui_logs = getattr(self, "_pre_ui_logs", [])
                self._pre_ui_logs.append(str(msg))
                return
            self.main_log.insert("end", f"{msg}\n")
            self.main_log.see("end")
        except Exception:
            pass

    def _append_dev_log_mirror(self, serial: str, msg: str):
        try:
            if not hasattr(self, "dev_log_view"):
                return
            if getattr(self, "current_log_serial", None) == serial:
                self.dev_log_view.insert("end", f"{msg}\n")
                self.dev_log_view.see("end")
        except Exception:
            pass

    def enqueue_to_tab(self, serial: str, msg: str):
        # 写入设备页签日志，并镜像到“设备日志”页；不再频繁自动切换日志标签
        self.after(0, lambda: self.device_tabs.get(serial) and self.device_tabs[serial].device_log(msg))
        self.after(0, lambda s=serial, m=msg: self._append_dev_log_mirror(s, m))
    def toggle_pause(self):
        """切换全局暂停/继续（类方法，供顶栏按钮调用）"""
        try:
            if not self.pause_event.is_set():
                self.pause_event.set()
                try:
                    self.pause_btn.configure(text="继续")
                except Exception:
                    pass
                try:
                    self.logger.info("[PAUSE] 全局暂停已开启")
                    self._append_timeline("[PAUSE] 全局暂停已开启")
                except Exception:
                    pass
            else:
                self.pause_event.clear()
                try:
                    self.pause_btn.configure(text="暂停")
                except Exception:
                    pass
                try:
                    self.logger.info("[PAUSE] 已继续运行")
                    self._append_timeline("[PAUSE] 已继续运行")
                except Exception:
                    pass
        except Exception:
            pass


    # ----------------- ADB 路径 -----------------
    def browse_adb(self):
        path = filedialog.askopenfilename(title="选择 adb.exe", filetypes=[("adb.exe", "adb.exe"), ("所有文件", "*.*")])
        if path:
            self.adb_path_var.set(path)

    def apply_adb_path(self):
        path = self.adb_path_var.get().strip()
        ok, out = self.adb.set_adb_path(path if path else None)
        if ok:
            self.cfg["adb_path"] = self.adb.adb_path
            self.config_mgr.save(self.cfg)
            messagebox.showinfo("ADB", f"已设置并保存 ADB：{self.adb.adb_path}")
        else:
            messagebox.showerror("ADB", f"失败：{out}")

    # ----------------- 折叠/展开 左侧设备区 -----------------
    def _toggle_left_pane(self):
        try:
            # 允许缩到 0 宽
            self.split.paneconfigure(self.left_pane, minsize=0)
        except Exception:
            pass
        if not getattr(self, "left_collapsed", False):
            # 折叠：记录当前宽度，推到最左
            try:
                self._left_saved_width = save_paned_width(self, self.split, 0, LEFT_DEFAULT_WIDTH)
            except Exception:
                self._left_saved_width = LEFT_DEFAULT_WIDTH
            try:
                self.split.sashpos(0, 0)
            except Exception:
                pass
            self.left_collapsed = True
            try:
                self.collapse_btn.configure(text="展开设备区")
            except Exception:
                pass
        else:
            # 展开：恢复原宽度（若无记录则用默认值）
            width = getattr(self, "_left_saved_width", LEFT_DEFAULT_WIDTH)
            restore_paned_width(self, self.split, 0, int(width))
            self.left_collapsed = False
            try:
                self.collapse_btn.configure(text="折叠设备区")
            except Exception:
                pass

    # ----------------- 全局速度 / 全局操作模式 -----------------
    def get_speed_factor(self) -> float:
        try:
            v = float((self.speed_factor_var.get() or "1.0").strip())
            if v <= 0:
                v = 1.0
        except Exception:
            v = 1.0
        return v

    def apply_speed_factor(self):
        v = self.get_speed_factor()
        self.cfg["speed_factor"] = v
        self.config_mgr.save(self.cfg)
        self.logger.info(f"已应用全局运行速度：x{v:.2f}")

    def is_global_multi_mode(self) -> bool:
        try:
            return bool(self.multi_mode_var.get())
        except Exception:
            return False

    def apply_multi_mode(self):
        self.cfg["global_multi"] = self.is_global_multi_mode()
        self.config_mgr.save(self.cfg)
        self.logger.info(f"已 {'开启' if self.cfg['global_multi'] else '关闭'} 全局操作模式")

    # ----------------- 设备管理 -----------------
    def refresh_devices(self):
        devs = self.adb.list_devices()
        current = set(self.workers.keys())
        incoming = set(devs)

        # 新增设备
        for s in incoming - current:
            w = DeviceWorker(serial=s, adb=self.adb, logger=self.logger)
            w.start()
            self.workers[s] = w
            self.logger.info(f"创建工作线程：{s}")

        # 离线设备
        for s in current - incoming:
            self.workers[s].stop()
            self.logger.warn(f"设备离线，停止工作线程：{s}")
            del self.workers[s]

        # 同步标签页：关闭离线、补齐在线
        # 先关闭已离线设备的标签
        for s in list(self.device_tabs.keys()):
            if s not in incoming:
                self._close_tab(s)
        # 为所有在线设备确保存在一个标签（无备注也会创建，标题用序列号）
        for s in sorted(incoming):
            self._create_or_update_tab(s)

        # 列表模式 UI 刷新
        if hasattr(self, "devices_list"):
            self.devices_list.delete(0, tk.END)
            for s in sorted(set(devs) | set(self.device_tabs.keys())):
                st = "在线" if s in incoming else "离线"
                note = self.cfg.get("notes", {}).get(s, "")
                self.devices_list.insert(tk.END, f"{s} [{st}]  {('— ' + note) if note else ''}")

        # 缩略图模式 UI 刷新（重建卡片）
        if getattr(self, "view_mode_var", None) and self.view_mode_var.get() == "thumb":
            self.thumb_grid.rebuild(self.cfg.get("notes", {}))

        # 标签页状态刷新
        for s, tab in self.device_tabs.items():
            tab.refresh_status()

        self.logger.info(f"当前在线 {len(incoming)} 台设备，打开标签 {len(self.device_tabs)}。")

    def _selected_serials(self) -> List[str]:
        """获取当前选中的设备序列号，支持列表和缩略图两种模式"""
        res: List[str] = []

        mode = self.view_mode_var.get() if getattr(self, "view_mode_var", None) else "list"
        if mode == "list":
            # 列表模式：从 Listbox 获取选中项
            for i in self.devices_list.curselection():
                item = self.devices_list.get(i)
                res.append(item.split()[0])
        else:
            # 缩略图模式：从当前选中的标签页获取设备（支持两行标签）
            curr = self.nb_content.select()
            if curr:
                for s, tab in self.device_tabs.items():
                    if str(tab) == curr:
                        res.append(s)
                        break

        return res

    def on_device_select(self, event=None):
        """设备选择事件处理，支持列表和缩略图两种模式"""
        serials = self._selected_serials()
        if len(serials) == 1:
            s = serials[0]
            note = self.cfg.get("notes", {}).get(s, "")
            # 同步更新两个模式的备注文本框
            self.note_text.delete("1.0", tk.END)
            self.note_text.insert(tk.END, note)
            self.thumb_note_text.delete("1.0", tk.END)
            self.thumb_note_text.insert(tk.END, note)
        else:
            # 清除两个模式的备注文本框
            self.note_text.delete("1.0", tk.END)
            self.thumb_note_text.delete("1.0", tk.END)

    def save_note_for_selected(self):
        serials = self._selected_serials()
        if not serials:
            messagebox.showwarning("备注", "请先选择一个设备")
            return

        # 根据当前模式从正确的文本框获取备注内容
        if self.view_mode_var.get() == "list":
            note = self.note_text.get("1.0", tk.END).strip()
        else:
            note = self.thumb_note_text.get("1.0", tk.END).strip()

        self.cfg.setdefault("notes", {})
        self.cfg.setdefault("devices", [])

        for s in serials:
            self.cfg["notes"][s] = note
            if s not in self.cfg["devices"]:
                self.cfg["devices"].append(s)
            self._create_or_update_tab(s)
        self.config_mgr.save(self.cfg)
        self.logger.info(f"已保存备注并同步标签页到 {len(serials)} 个设备。")
        self.refresh_devices()

    # ----------------- 标签页 -----------------
    def _rebuild_tabs_from_config(self):
        for s in self.cfg.get("devices", []):
            self._create_or_update_tab(s)

    def _create_or_update_tab(self, serial: str):
        def _wrap_title(txt: str, width: int = 8) -> str:
            t = (txt or "").strip()
            if not t:
                return serial
            return "\n".join([t[i:i+width] for i in range(0, len(t), width)])
        note = self.cfg.get("notes", {}).get(serial, "")
        title = _wrap_title(note) if note.strip() else serial

        if serial in self.device_tabs:
            tab = self.device_tabs[serial]
            try:
                if serial in self.tab_buttons:
                    self.tab_buttons[serial].configure(text=title)
            except Exception:
                pass
            tab.refresh_status()
            self._rebuild_tab_header()
            return

        # 新建：加入单一内容区（隐藏页签的 Notebook），页签头由自绘两行按钮承担
        tab = DeviceTab(self.nb_content, self, serial)
        self.nb_content.add(tab, text=title)
        self.device_tabs[serial] = tab
        if serial not in self.cfg.get("devices", []):
            self.cfg.setdefault("devices", []).append(serial)
        self._rebuild_tab_header()

    def _nb_of_tab(self, tab_widget) -> ttk.Notebook | None:
        # 兼容旧代码：现统一为内容区 Notebook
        return getattr(self, "nb_content", None)

    def _select_tab(self, serial: str):
        tab = self.device_tabs.get(serial)
        if not tab:
            return
        try:
            self.nb_content.select(tab)
            self._update_header_selection()
            self._sync_dev_log_view()
        except Exception:
            pass

    def _close_tab(self, serial: str):
        tab = self.device_tabs.pop(serial, None)
        if tab is not None:
            try:
                nb = self._nb_of_tab(tab) or self.nb1
                nb.forget(tab)
                tab.destroy()
            except Exception:
                pass
        # 
        self._update_tab_rows_visibility()

    def _on_tab_changed(self, event=None):
        """标签页切换事件处理（支持两行 Notebook）"""
        try:
            curr = self.nb_content.select()
        except Exception:
            curr = None
        if not curr:
            return
        # 同步左侧“设备日志”页内容 + 页签头选中态
        self._sync_dev_log_view()
        self._update_header_selection()

        # 查找当前选中的设备序列号
        serial = None
        for s, tab in self.device_tabs.items():
            if str(tab) == curr:
                serial = s
                break

        if serial and getattr(self, "view_mode_var", None) and self.view_mode_var.get() == "thumb":
            self.thumb_grid.refresh_one_async(serial)

    # ----------------- 标签排序/拖拽 -----------------
    def _enable_tab_drag_sort(self):
        self._drag_tab_index = None
        def on_press(event):
            try:
                self._drag_tab_index = self.nb.index(f"@{event.x},{event.y}")
            except Exception:
                self._drag_tab_index = None
        def on_release(event):
            if self._drag_tab_index is None:
                return
            try:
                new_index = self.nb.index(f"@{event.x},{event.y}")
            except Exception:
                new_index = None


            if new_index is None:
                self._drag_tab_index = None
                return
            if new_index != self._drag_tab_index:
                tab_id = self.nb.tabs()[self._drag_tab_index]
                self.nb.insert(new_index, tab_id)
                self._save_tab_order_to_config()
            self._drag_tab_index = None
        self.nb.bind("<ButtonPress-1>", on_press, add="+")
        self.nb.bind("<ButtonRelease-1>", on_release, add="+")

    def _save_tab_order_to_config(self):
        order_serials = []
        id_to_serial = {str(tab): s for s, tab in self.device_tabs.items()}
        for tid in list(self.nb_content.tabs()):
            s = id_to_serial.get(tid)
            if s:
                order_serials.append(s)
        self.cfg["devices"] = order_serials
        self.config_mgr.save(self.cfg)


    def _update_tab_rows_visibility(self):
        """
        自绘两行页签头：当设备数不超过 13 时隐藏第二行；超过则显示。
        """
        try:
            total = len(self.cfg.get("devices", list(self.device_tabs.keys())))
            if total <= 13:
                try:
                    self.tab_header_row2.pack_forget()
                except Exception:
                    pass
            else:
                if not self.tab_header_row2.winfo_ismapped():
                    self.tab_header_row2.pack(fill=tk.X, expand=False)
        except Exception:
            pass

    def sort_tabs_toggle(self):
        mode = getattr(self, "tab_sort_by", "serial")
        # 计算排序键
        def key_serial(s):
            return s
        def key_note(s):
            return (self.cfg.get("notes", {}).get(s, "") or "")
        serials = list(self.device_tabs.keys())
        if mode == "serial":
            serials.sort(key=key_serial)
            self.tab_sort_by = "note"
            self.logger.info("标签排序：按设备名称（升序）")
        else:
            serials.sort(key=key_note)
            self.tab_sort_by = "serial"
            self.logger.info("标签排序：按备注名称（升序）")
        # 按排序结果重排内容区 Notebook，并重建自绘页签头
        tab_ids = {s: self.device_tabs[s] for s in self.device_tabs}
        for s in list(tab_ids.keys()):
            try:
                self.nb_content.forget(tab_ids[s])
            except Exception:
                pass
        def _wrap(t: str, width: int = 8) -> str:
            t = (t or "").strip()
            if not t:
                return ""
            return "\n".join([t[i:i+width] for i in range(0, len(t), width)])
        for s in serials:
            note = self.cfg.get("notes", {}).get(s, "")
            title = _wrap(note) if note.strip() else s
            try:
                self.nb_content.add(tab_ids[s], text=title)
            except Exception:
                pass
        self.cfg["devices"] = serials
        self._rebuild_tab_header()
        self._update_tab_rows_visibility()
        self.config_mgr.save(self.cfg)


    # ----------------- 连接/断开/关闭 -----------------
    def auto_connect_mumu(self):
        """自动连接MuMu模拟器，使用多线程并行扫描端口范围"""
        self.logger.info("开始并行扫描MuMu模拟器...")

        # 禁用按钮避免重复点击
        self._disable_auto_connect_button()

        # 在后台线程中执行扫描
        threading.Thread(target=self._scan_mumu_ports_parallel, daemon=True).start()

    def _disable_auto_connect_button(self):
        """禁用自动连接按钮"""
        for widget in self.winfo_children():
            if isinstance(widget, ttk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Button) and child.cget("text") == "自动连接MuMu":
                        child.configure(state="disabled")
                        self._auto_connect_button = child
                        break

    def _enable_auto_connect_button(self):
        """启用自动连接按钮"""
        if hasattr(self, '_auto_connect_button'):
            self._auto_connect_button.configure(state="normal")

    def _scan_mumu_ports_parallel(self):
        """并行扫描MuMu端口范围"""
        connected_count = 0
        start_port = 16384
        end_port = 17664
        step = 32

        # 按需求：从 16416 开始，步长 32，共 30 个端口
        base = 16416
        ports = [base + step * i for i in range(30)]
        total_ports = len(ports)

        self.logger.info(f"开始并行扫描特定端口 {total_ports} 个（起始16416，步长32，共30个）...")

        # 使用线程池并行扫描
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            # 提交所有扫描任务
            future_to_port = {
                executor.submit(self._try_connect_port, port): port
                for port in ports
            }

            # 收集结果
            for future in concurrent.futures.as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    success = future.result()
                    if success:
                        connected_count += 1
                except Exception as e:
                    self.logger.error(f"扫描端口 {port} 时出错: {e}")

        # 在主线程中更新UI
        self.after(0, self._on_scan_complete, connected_count, total_ports)

    def _try_connect_port(self, port):
        """尝试连接单个端口"""
        ipport = f"127.0.0.1:{port}"
        ok, out = self.adb.connect(ipport)
        if ok:
            self.logger.info(f"成功连接: {ipport}")
            return True
        else:
            # 只记录非"无法连接"的错误
            if "cannot connect" not in out.lower() and "failed to connect" not in out.lower():
                self.logger.info(f"连接失败 {ipport}: {out}")
            return False

    def _on_scan_complete(self, connected_count, total_ports):
        """扫描完成后的回调"""
        self.logger.info(f"并行扫描完成，成功连接 {connected_count}/{total_ports} 个MuMu设备")
        # 启用按钮
        self._enable_auto_connect_button()
        # 刷新设备列表并将所有在线设备加入标签页
        def do_refresh_and_tabs():
            self.refresh_devices()
            # 自动把当前在线设备全部加入标签页
            self.cfg.setdefault("devices", [])
            changed = False
            for s in list(self.workers.keys()):
                if s not in self.cfg["devices"]:
                    self.cfg["devices"].append(s)
                    changed = True
                self._create_or_update_tab(s)
            # 清理不存在或断开的设备标签
            for s in list(self.device_tabs.keys()):
                if s not in self.workers:
                    self._close_tab(s)
                    if s in self.cfg["devices"]:
                        self.cfg["devices"].remove(s)
                    changed = True
            if changed:
                self.config_mgr.save(self.cfg)
            # 开启标签拖动排序支持（若尚未绑定）
            try:
                self._enable_tab_drag_sort()
            except Exception:
                pass
        self.after(500, do_refresh_and_tabs)

    def connect_ip_port(self):
        ipport = self.ip_port_var.get().strip()
        ok, out = self.adb.connect(ipport)
        if ok:
            self.logger.info(out)
            self.refresh_devices()
        else:
            self.logger.error(out)

    # ----------------- 任务互斥与优先级 -----------------
    def register_task(self, key: str, stop_event, resume_cb, button=None):
        # 若存在潜在冲突（除离线监控外），启动前先停止同类或冲突任务
        if key != "global:offline_monitor":
            self.stop_other_tasks_before_start(key)
        self.running_tasks[key] = {"stop_event": stop_event, "resume": resume_cb, "button": button}

    def unregister_task(self, key: str):
        self.running_tasks.pop(key, None)

    def stop_other_tasks_before_start(self, new_key: str):
        # 离线监控具有最高优先级；若其正在一轮修复中，不允许其他任务启动
        if self._offmon_round_active:
            raise RuntimeError("离线修复进行中，已阻止启动其他任务")

        # 解析作用域：serial:task / global:xxx / garrison:ALL 等
        # 注意：serial 可能包含冒号（如 127.0.0.1:7555），因此必须从右侧分割一次
        def _scope(key: str) -> str:
            return (key.rsplit(":", 1)[0] if ":" in key else key) or ""

        new_scope = _scope(new_key)

        for k, info in list(self.running_tasks.items()):
            if k == new_key:
                continue
            k_scope = _scope(k)
            try:
                # 全局/分组任务（如 garrison:ALL）默认与所有任务互斥；但保留离线监控
                if new_scope in ("global", "garrison") or k_scope in ("global", "garrison"):
                    if k == "global:offline_monitor":
                        continue
                    ev = info.get("stop_event")
                    if ev:
                        ev.set()
                    continue
                # 普通设备任务：仅对同设备(serial)的其它任务互斥，允许不同设备并行
                if new_scope == k_scope:
                    ev = info.get("stop_event")
                    if ev:
                        ev.set()
            except Exception:
                pass

    def _suspend_all_tasks_for_offmon(self):
        # 离线监测触发修复：停止所有正在运行的任务（除自身）并记录 resume 回调
        self._suspended_for_offmon.clear()
        for k, info in list(self.running_tasks.items()):
            if k == "global:offline_monitor":
                continue
            try:
                ev = info.get("stop_event")
                if ev:
                    ev.set()
            except Exception:
                pass
            res = info.get("resume")
            if res:
                self._suspended_for_offmon.append(res)
        self._offmon_round_active = True

    def _resume_suspended_after_offmon(self):
        # 在一轮修复完成后，按顺序恢复先前暂停的任务
        for res in list(self._suspended_for_offmon):
            try:
                res()
            except Exception:
                pass
        self._suspended_for_offmon.clear()
        self._offmon_round_active = False

    def disconnect_selected(self):
        """断开选中的设备连接，支持列表和缩略图两种模式"""
        serials = self._selected_serials()
        if not serials:
            messagebox.showwarning("断开连接", "请先选择一个设备")
            return

        for s in serials:
            ok, out = self.adb.disconnect(s)
            if ok:
                self.logger.info(f"已断开：{s}")
                if s in self.workers:
                    try:
                        self.workers[s].stop()
                    except Exception:
                        pass
                    self.workers.pop(s, None)
                # 关闭标签并从保存列表移除
                self._close_tab(s)
                if "devices" in self.cfg and s in self.cfg["devices"]:
                    self.cfg["devices"].remove(s)
                self.config_mgr.save(self.cfg)
            else:
                self.logger.error(f"断开失败 {s}: {out}")
        self.after(200, self.refresh_devices)

    def _apply_view_mode(self, initial: bool = False):
        mode = self.view_mode_var.get() if getattr(self, "view_mode_var", None) else self.cfg.get("device_view_mode", "list")
        self.cfg["device_view_mode"] = mode
        self.config_mgr.save(self.cfg)

        # 清理现有 packing
        for w in (self.list_frame, self.thumb_frame):
            try:
                w.pack_forget()
            except Exception:
                pass

        # 停止旧的周期刷新
        self.thumb_grid.cancel_timer()

        if mode == "list":
            self.list_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.thumb_frame.pack(fill=tk.BOTH, expand=True)
            self.thumb_grid.rebuild(self.cfg.get("notes", {}))
            # 立即刷新当前标签对应设备（若有）
            self._on_tab_changed()

    def on_close(self):
        try:
            # 保存分栏位置与窗口尺寸
            left_width = save_paned_width(self, self.split, 0, default_=LEFT_DEFAULT_WIDTH)
            self.cfg.setdefault("layout", {})
            self.cfg["layout"]["split_left"] = int(left_width)
            self.cfg["geometry"] = self.geometry()
            self.config_mgr.save(self.cfg)
            self.thumb_grid.cancel_timer()
        finally:
            self.destroy()


    # ----------------- 标签列表菜单 -----------------
    def show_tab_list_menu(self):
        menu = tk.Menu(self, tearoff=0)
        # 设备序列按当前标签顺序展示
        for s in self.cfg.get("devices", list(self.device_tabs.keys())):
            if s in self.device_tabs:
                menu.add_command(label=s, command=lambda ss=s: self._select_tab(ss))
        # 若没有设备
        if not menu.index("end"):
            menu.add_command(label="无标签", state="disabled")
        # 弹出到按钮下方
        try:
            x = self.tab_list_btn.winfo_rootx()
            y = self.tab_list_btn.winfo_rooty() + self.tab_list_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _select_tab(self, serial: str):
        tab = self.device_tabs.get(serial)
        if tab is not None:
            try:
                self.nb_content.select(tab)
                self._update_header_selection()
                self._sync_dev_log_view()
            except Exception:
                pass

    def force_stop_all_safe(self):
        """一键停止并重启主程序：
        - 立即广播强停标志，停止所有任务（含离线监控）
        - 停止各设备工作线程
        - 以原启动参数就地重启进程，确保按钮状态/UI完全复原
        """
        # 1) 广播全局强停标志（供无按钮子任务轮询）
        try:
            setattr(self, "_force_stop_all", True)
        except Exception:
            pass

        from .helpers.task_utils import TaskUtils as _TU
        # 2) 停止离线监控
        try:
            ev = getattr(self, "_offline_mon_stop_ev", None)
            if ev is not None:
                _TU.stop_task(ev, getattr(self, "offmon_btn", None))
        except Exception:
            pass
        # 3) 停止所有已注册任务（按钮置灰 → 背景线程尽快退出）
        try:
            items = list(self.running_tasks.items())
        except Exception:
            items = []
        for key, info in items:
            try:
                ev = info.get("stop_event") if isinstance(info, dict) else None
                btn = info.get("button") if isinstance(info, dict) else None
                if ev is not None:
                    _TU.stop_task(ev, btn)
            except Exception:
                pass
        # 4) 停止所有设备工作线程
        try:
            for w in list(self.workers.values()):
                try:
                    w.stop()
                except Exception:
                    pass
        except Exception:
            pass

        # 禁用“停止运行”按钮，防止重复点击
        try:
            self.emergency_stop_btn.configure(state="disabled")
        except Exception:
            pass

        # 5) 延迟少许，原地重启进程（Windows/Tk 下更稳妥）
        def _restart():
            try:
                # 保存必要的配置（如窗口尺寸/布局）
                try:
                    left_width = save_paned_width(self, self.split, 0, default_=LEFT_DEFAULT_WIDTH)
                    self.cfg.setdefault("layout", {})
                    self.cfg["layout"]["split_left"] = int(left_width)
                    self.cfg["geometry"] = self.geometry()
                    self.config_mgr.save(self.cfg)
                except Exception:
                    pass
                os.execl(sys.executable, sys.executable, *sys.argv)
            except Exception:
                # 回退：若重启失败，至少清掉强停标志，避免无法再启动任务
                try:
                    setattr(self, "_force_stop_all", False)
                except Exception:
                    pass
        # 500ms 后执行重启，给后台线程一点退出时间
        try:
            self.after(500, _restart)
        except Exception:
            _restart()

