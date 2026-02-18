# mumu_adb_controller/ui/device_tab.py
from tkinter import ttk
import tkinter as tk
import threading
import time
import datetime as _dt

# 业务与工具
from .toast import show_toast
from .helpers.tool_launcher import launch_ui_cropper
from .helpers.task_utils import TaskUtils
from .tasks.init_to_wild import run_init_to_wild
from .tasks.sweep_army import run_sweep_army
from .tasks.sweep_fort import run_sweep_fort  # ★ 新增：刷王城/炮台任务
from .tasks.sweep_hunt import run_sweep_hunt  # ★ 新增：打野任务
from .tasks.withdraw_troops import run_withdraw_troops  # ★ 新增：一键撤军任务
from .tasks.auto_garrison import (
    run_auto_garrison,
    run_close_alliance_help,
    run_open_alliance_help,
)
from .tasks.auto_like import run_auto_like
from .tasks.emergency_heal import run_emergency_heal
from ..tasks.new_troop_selection import run_new_troop_selection  # ★ 新增：智能选兵任务
from .tasks.fast_join_rally import run_fast_join_rally  # ★ 新增：秒进集结
from .tasks.attack_resources import run_attack_resources  # ★ 新增：打资源
from .tasks.promote_rank4 import run_promote_rank4  # ★ 新增：一键四阶
from .tasks.bear_mode import run_bear_mode, BearOptions  # ★ 新增：打熊模式
from .helpers import matcher


class DeviceTab(ttk.Frame):
    """
    设备页（美化版）：
    - 设备操作（卡片）：刷王城/炮台（直接开始/停止） / 刷全军（公告 + 开始/停止）
    - 设备日志（卡片）
    - 小工具（卡片）：获取坐标 / 截图辅助工具与匹配测试 / 智能选兵 / 初始化到野外
    """
    def __init__(self, master, app, serial: str):
        super().__init__(master)
        self.app = app
        self.serial = serial

        # 智能选兵状态管理
        self.smart_troop_running = False
        self.smart_troop_thread = None
        self.smart_troop_stop_flag = False

        self.columnconfigure(0, weight=1)
        row = 0

        head = ttk.Frame(self, padding=(6, 6, 6, 2))
        head.grid(row=row, column=0, sticky="ew")
        row += 1
        self.title_var = tk.StringVar(value=f"设备：{serial}（离线）")
        ttk.Label(head, textvariable=self.title_var).pack(side=tk.LEFT)

        # 创建左右并排布局的容器
        dual_box = ttk.Frame(self)
        dual_box.grid(row=row, column=0, sticky="ew", padx=8, pady=6)
        row += 1
        dual_box.columnconfigure(0, weight=1)
        dual_box.columnconfigure(1, weight=1)

        # 左：出征+治疗
        outing_box = ttk.Labelframe(dual_box, text="出征+治疗", padding=12, style="Card.TLabelframe")
        outing_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=0)
        outing_box.columnconfigure(0, weight=1)

        mode_row = ttk.Frame(outing_box)
        mode_row.grid(row=0, column=0, sticky="w")
        ttk.Label(mode_row, text="任务类型").pack(side=tk.LEFT)
        self.outing_mode_var = tk.StringVar(value="army")
        ttk.Radiobutton(
            mode_row,
            text="刷全军",
            variable=self.outing_mode_var,
            value="army",
            command=self._update_outing_mode,
        ).pack(side=tk.LEFT, padx=(6, 8))
        ttk.Radiobutton(
            mode_row,
            text="王城/炮台",
            variable=self.outing_mode_var,
            value="fort",
            command=self._update_outing_mode,
        ).pack(side=tk.LEFT)

        self.army_panel = ttk.Frame(outing_box)
        self.army_panel.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.army_panel.columnconfigure(1, weight=1)
        # 出征参数：两行布局。第一行：持续秒数/循环次数；第二行：总时长(秒)/调试间隔(s)
        self.sweep_seconds = tk.StringVar(value="8")
        self.sweep_loops = tk.StringVar(value="1")
        self.sweep_total = tk.StringVar(value="0")
        self.sweep_step_delay = tk.StringVar(value="0.10")
        row1 = ttk.Frame(self.army_panel)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="持续秒数").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.sweep_seconds, width=6).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row1, text="循环次数").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.sweep_loops, width=5).pack(side=tk.LEFT, padx=(6, 0))
        row2 = ttk.Frame(self.army_panel)
        row2.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(row2, text="总时长(秒)").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.sweep_total, width=8).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row2, text="调试间隔(s)").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.sweep_step_delay, width=6).pack(side=tk.LEFT, padx=(6, 0))

        self.fort_panel = ttk.Frame(outing_box)
        self.fort_panel.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.fort_panel.columnconfigure(1, weight=1)
        ttk.Label(self.fort_panel, text="目标").grid(row=0, column=0, sticky="w")
        self.fort_mode = tk.StringVar(value="fort")
        fort_mode_row = ttk.Frame(self.fort_panel)
        fort_mode_row.grid(row=0, column=1, sticky="w", padx=(6, 16))
        ttk.Radiobutton(fort_mode_row, text="炮台", variable=self.fort_mode, value="fort").pack(side=tk.LEFT)
        ttk.Radiobutton(fort_mode_row, text="王城", variable=self.fort_mode, value="city").pack(side=tk.LEFT, padx=(8, 0))
        # 治疗参数：两行布局。第一行：治疗秒数/循环次数；第二行：调试间隔(s)
        self.fort_seconds = tk.StringVar(value="8")
        self.fort_loops = tk.StringVar(value="1")
        self.fort_step_delay = tk.StringVar(value="0.10")
        fort_row1 = ttk.Frame(self.fort_panel)
        fort_row1.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(fort_row1, text="治疗秒数").pack(side=tk.LEFT)
        ttk.Entry(fort_row1, textvariable=self.fort_seconds, width=6).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(fort_row1, text="循环次数").pack(side=tk.LEFT)
        ttk.Entry(fort_row1, textvariable=self.fort_loops, width=5).pack(side=tk.LEFT, padx=(6, 0))
        fort_row2 = ttk.Frame(self.fort_panel)
        fort_row2.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(fort_row2, text="调试间隔(s)").pack(side=tk.LEFT)
        ttk.Entry(fort_row2, textvariable=self.fort_step_delay, width=6).pack(side=tk.LEFT, padx=(6, 0))

        self.outing_btn = ttk.Button(outing_box, text="开始刷全军", command=self._btn_outing)
        self.outing_btn.grid(row=2, column=0, sticky="w", pady=(8, 0))

        # 自动驻军与联盟功能放置在“出征+治疗”下方
        garrison_row = ttk.Frame(outing_box)
        garrison_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        garrison_row.columnconfigure(0, weight=1)
        garrison_row.columnconfigure(1, weight=1)

        # 左：自动驻军
        garrison_box = ttk.Labelframe(garrison_row, text="自动驻军", padding=8, style="Card.TLabelframe")
        garrison_box.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Label(garrison_box, text="驻军模式").pack(side=tk.LEFT)
        self.garrison_mode_var = tk.StringVar(value="乔伊")
        self.garrison_mode_cb = ttk.Combobox(garrison_box, width=6, textvariable=self.garrison_mode_var, values=("乔伊", "收菜"), state="readonly")
        self.garrison_mode_cb.pack(side=tk.LEFT, padx=(6, 8))
        self.garrison_btn = ttk.Button(garrison_box, text="开始自动驻军", command=self._btn_auto_garrison)
        self.garrison_btn.pack(side=tk.LEFT)
        # 紧急治疗按钮并入自动驻军模块，靠近开始按钮
        self.emergency_heal_btn = ttk.Button(garrison_box, text="紧急治疗", command=self._btn_emergency_heal)
        self.emergency_heal_btn.pack(side=tk.LEFT, padx=(6, 0))

        # 燃霜模式单独一行
        ranshuang_row = ttk.Frame(outing_box)
        ranshuang_row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ranshuang_box = ttk.Labelframe(ranshuang_row, text="燃霜模式", padding=8, style="Card.TLabelframe")
        ranshuang_box.pack(fill=tk.X)
        self.ranshuang_btn = ttk.Button(ranshuang_box, text="开始燃霜模式", command=self._btn_ranshuang)
        self.ranshuang_btn.pack(side=tk.LEFT)

        # 联盟功能单独一行
        alliance_row = ttk.Frame(outing_box)
        alliance_row.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        alliance_box = ttk.Labelframe(alliance_row, text="联盟功能", padding=8, style="Card.TLabelframe")
        alliance_box.pack(fill=tk.X)
        ttk.Button(alliance_box, text="关闭上车", width=8, command=self._btn_close_alliance_help).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(alliance_box, text="打开上车", width=8, command=self._btn_open_alliance_help).pack(side=tk.LEFT, padx=(0, 4))
        self.auto_like_btn = ttk.Button(alliance_box, text="自动点赞", width=8, command=self._btn_auto_like)
        self.auto_like_btn.pack(side=tk.LEFT, padx=(0, 4))
        # 将“秒进集结”移入联盟功能
        self.fast_join_btn = ttk.Button(alliance_box, text="秒进集结", width=8, command=self._btn_fast_join)
        self.fast_join_btn.pack(side=tk.LEFT, padx=(0, 4))
        # 新增：一键四阶
        self.promote_rank4_btn = ttk.Button(alliance_box, text="一键四阶", width=8, command=self._btn_promote_rank4)
        self.promote_rank4_btn.pack(side=tk.LEFT, padx=(0, 4))


        # 右：打熊 / 打野 / 打资源
        right_col = ttk.Frame(dual_box)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=0)

        bear_box = ttk.Labelframe(right_col, text="打熊模式", padding=(8, 6), style="Card.TLabelframe")
        bear_box.pack(fill=tk.X)
        for col in range(6):
            bear_box.columnconfigure(col, weight=1 if col in (1, 3, 5) else 0)
        ttk.Label(bear_box, text="打熊时间(HHMMSS)").grid(row=0, column=0, sticky="w")
        self.bear_time_var = tk.StringVar(value="203000")
        ttk.Entry(bear_box, textvariable=self.bear_time_var, width=8, justify="center").grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(bear_box, text="执行日").grid(row=0, column=2, sticky="e")
        self.bear_day_mode_map = {"单双日皆打": "both", "仅单日": "odd", "仅双日": "even"}
        self.bear_day_mode_var = tk.StringVar(value="单双日皆打")
        ttk.Combobox(
            bear_box,
            textvariable=self.bear_day_mode_var,
            state="readonly",
            width=8,
            values=tuple(self.bear_day_mode_map.keys()),
        ).grid(row=0, column=3, sticky="w")
        self.bear_send_car_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bear_box, text="主动发车", variable=self.bear_send_car_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(bear_box, text="车头模式").grid(row=1, column=2, sticky="e", pady=(4, 0))
        self.bear_head_mode_map = {"固定车头": "fixed", "随机上车": "random"}
        self.bear_head_mode_var = tk.StringVar(value="随机上车")
        ttk.Combobox(
            bear_box,
            textvariable=self.bear_head_mode_var,
            state="readonly",
            width=8,
            values=tuple(self.bear_head_mode_map.keys()),
        ).grid(row=1, column=3, sticky="w", pady=(4, 0))
        ttk.Label(bear_box, text="发车间隔(秒)").grid(row=1, column=4, sticky="e", pady=(4, 0))
        self.bear_interval_var = tk.StringVar(value="300")
        ttk.Entry(bear_box, textvariable=self.bear_interval_var, width=6).grid(row=1, column=5, sticky="w", padx=(4, 0), pady=(4, 0))
        self._load_bear_defaults()
        self.bear_btn = ttk.Button(bear_box, text="启动打熊模式", command=self._btn_bear_mode)
        self.bear_btn.grid(row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))

        hunt_box = ttk.Labelframe(right_col, text="打野参数", padding=(8, 6), style="Card.TLabelframe")
        hunt_box.pack(fill=tk.X, pady=(8, 0))
        hunt_box.columnconfigure(0, weight=1)
        hunt_box.columnconfigure(1, weight=1)
        self.hunt_btn = ttk.Button(hunt_box, text="开始打野", command=self._btn_sweep_hunt)
        self.hunt_btn.grid(row=0, column=0, sticky="w", pady=(0, 4))

        hunt_type_frame = ttk.Frame(hunt_box)
        hunt_type_frame.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(hunt_type_frame, text="打野类型").pack(side=tk.LEFT)
        self.hunt_type = tk.StringVar(value="beast")
        ttk.Radiobutton(hunt_type_frame, text="野兽", variable=self.hunt_type, value="beast").pack(side=tk.LEFT, padx=(6, 6))
        ttk.Radiobutton(hunt_type_frame, text="巨兽", variable=self.hunt_type, value="monster").pack(side=tk.LEFT)

        beast_frame = ttk.Frame(hunt_box)
        beast_frame.grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(beast_frame, text="野兽级别").pack(side=tk.LEFT)
        self.beast_30_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(beast_frame, text="30级", variable=self.beast_30_var).pack(side=tk.LEFT, padx=(6, 4))
        self.beast_26_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(beast_frame, text="26级", variable=self.beast_26_var).pack(side=tk.LEFT, padx=(0, 4))

        monster_frame = ttk.Frame(hunt_box)
        monster_frame.grid(row=1, column=1, sticky="w", pady=(2, 0))
        ttk.Label(monster_frame, text="巨兽级别").pack(side=tk.LEFT)
        self.monster_8_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(monster_frame, text="8级", variable=self.monster_8_var).pack(side=tk.LEFT, padx=(6, 4))
        self.monster_7_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(monster_frame, text="7级", variable=self.monster_7_var).pack(side=tk.LEFT, padx=(0, 4))
        self.monster_6_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(monster_frame, text="6级", variable=self.monster_6_var).pack(side=tk.LEFT, padx=(0, 4))
        self.monster_5_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(monster_frame, text="5级", variable=self.monster_5_var).pack(side=tk.LEFT)

        team_row = ttk.Frame(hunt_box)
        team_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Label(team_row, text="编队").pack(side=tk.LEFT)
        self.team_vars = {}
        for i in range(1, 9):
            var = tk.BooleanVar(value=False)
            self.team_vars[i] = var
            pad = (6, 0) if i == 1 else (4, 0)
            ttk.Checkbutton(team_row, text=f"{i}队", variable=var).pack(side=tk.LEFT, padx=pad)

        param_row = ttk.Frame(hunt_box)
        param_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Label(param_row, text="循环次数").pack(side=tk.LEFT)
        self.hunt_loops = tk.StringVar(value="1")
        ttk.Entry(param_row, textvariable=self.hunt_loops, width=5).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(param_row, text="调试间隔(s)").pack(side=tk.LEFT)
        self.hunt_step_delay = tk.StringVar(value="0.10")
        ttk.Entry(param_row, textvariable=self.hunt_step_delay, width=6).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(param_row, text="体力罐头").pack(side=tk.LEFT)
        self.hunt_can_count = tk.StringVar(value="0")
        ttk.Entry(param_row, textvariable=self.hunt_can_count, width=6).pack(side=tk.LEFT, padx=(6, 0))



        # 设备标签下的“设备日志”面板已移除；日志镜像在右侧日志栏体现
        # 仍保留一个隐藏的 Text 以承载设备日志内容，供右侧“设备日志”页镜像读取
        self.rowconfigure(row, weight=0)
        self.log_text = tk.Text(self, wrap="word", height=1, bd=0, highlightthickness=0)
        try:
            self.log_text.place_forget()
        except Exception:
            pass

        # 独立模块：打资源（与联盟/驻军同级的功能体系）
        resource_box = ttk.Labelframe(right_col, text="打资源", padding=12, style="Card.TLabelframe")
        resource_box.pack(fill=tk.X, pady=(8, 0))
        res_btn_row = ttk.Frame(resource_box)
        res_btn_row.pack(anchor="w")
        ttk.Button(res_btn_row, text="编辑资源坐标", command=self._btn_edit_attack_coords).pack(side=tk.LEFT, padx=(0, 8))
        self.attack_btn = ttk.Button(res_btn_row, text="打资源", command=self._btn_attack_resources)
        self.attack_btn.pack(side=tk.LEFT)

        # 等待超时处理选项（中文显示，内部保存英文码）
        opt_row = ttk.Frame(resource_box)
        opt_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(opt_row, text="等待超时处理：").pack(side=tk.LEFT)
        # code -> label
        self.attack_timeout_display_map = {
            "continue": "继续下一轮攻击",
            "skip": "跳过当前坐标，换下一个坐标",
            "abort": "终止任务",
        }
        # label -> code
        self.attack_timeout_reverse_map = {v: k for k, v in self.attack_timeout_display_map.items()}
        current_code = self.app.cfg.get("attack_on_timeout", "continue")
        current_label = self.attack_timeout_display_map.get(current_code, self.attack_timeout_display_map["continue"])
        self.attack_timeout_action_var = tk.StringVar(value=current_label)
        cb = ttk.Combobox(
            opt_row,
            textvariable=self.attack_timeout_action_var,
            width=16,
            state="readonly",
            values=tuple(self.attack_timeout_display_map.values()),
        )
        cb.pack(side=tk.LEFT, padx=(6, 0))
        def _save_timeout_action(*_):
            try:
                label = self.attack_timeout_action_var.get()
                code = self.attack_timeout_reverse_map.get(label, "continue")
                self.app.cfg["attack_on_timeout"] = code
                self.app.config_mgr.save(self.app.cfg)
            except Exception:
                pass
        cb.bind("<<ComboboxSelected>>", _save_timeout_action)

        tools = ttk.Labelframe(self, text="小工具", padding=10, style="Card.TLabelframe")
        tools.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))

        ttk.Button(tools, text="截图辅助工具与匹配测试", command=self._btn_launch_cropper).pack(side=tk.LEFT, padx=6, pady=4)
        ttk.Button(tools, text="初始化到野外", command=self._btn_init_to_wild).pack(side=tk.LEFT, padx=6, pady=4)
        self.withdraw_btn = ttk.Button(tools, text="一键撤军", command=self._btn_withdraw_troops)
        self.withdraw_btn.pack(side=tk.LEFT, padx=6, pady=4)

        # 坐标文本：从配置中恢复（按设备序列号）
        try:
            cfg = getattr(self.app, "cfg", {}) or {}
            self.attack_coords_text = (cfg.get("attack_coords", {}).get(self.serial) or "")
        except Exception:
            self.attack_coords_text = ""

        self._update_outing_mode()
        self.refresh_status()
    # ---------------- 公共 ----------------
    def _toast(self, text: str, ms: int = 2000):
        show_toast(self.winfo_toplevel(), text=text, ms=ms)

    def device_log(self, msg: str, level: str = "INFO"):
        # 兼容旧调用：忽略 level 参数，保持向后兼容
        self.log_text.insert("end", f"{msg}\n")
        self.log_text.see("end")

    def refresh_status(self):
        online = self.serial in self.app.workers
        self.title_var.set(f"设备：{self.serial}（{'在线' if online else '离线'}）")

    def _ensure_online(self) -> bool:
        if self.serial not in self.app.workers:
            self._toast("设备不在线，无法执行")
            return False
        return True
    def _for_each_target_tab(self, fn):
        """在全局操作模式下，对所有在线设备标签执行 fn(tab)；否则仅当前标签。"""
        try:
            multi = bool(self.app.is_global_multi_mode())
        except Exception:
            multi = False
        tabs = list(self.app.device_tabs.values()) if multi else [self]
        for tab in tabs:
            if tab.serial in self.app.workers:
                try:
                    fn(tab)
                except Exception:
                    pass


    def _start_task_with_button(self, task_id: str, button: ttk.Button, runner):
        if not self._ensure_online():
            return
        stop_attr = f"_{task_id}_stop_ev"
        stop_event = TaskUtils.create_stop_event()
        setattr(self, stop_attr, stop_event)

        def should_stop():
            event = getattr(self, stop_attr, stop_event)
            return event.is_set()

        stop_cmd = lambda: self._stop_task(stop_attr, button)
        TaskUtils.setup_task_button(button, stop_attr, stop_cmd)

        # 与离线监控/其他任务的互斥控制与自动恢复
        key = f"{self.serial}:{task_id}"
        resume_cb = lambda: self._start_task_with_button(task_id, button, runner)
        try:
            # 若离线修复进行中，将抛出异常并阻止启动
            self.app.register_task(key, stop_event, resume_cb, button)
        except Exception as e:
            try:
                self._toast(str(e))
            except Exception:
                pass
            # 还原按钮到初始状态
            try:
                swap = getattr(button, "_running_swap_btn", None)
                if swap is not None:
                    try:
                        swap.destroy()
                    except Exception:
                        pass
                    try:
                        delattr(button, "_running_swap_btn")
                    except Exception:
                        pass
                button.config(text=getattr(button, 'original_text', button.cget('text')),
                              command=getattr(button, 'original_command', button.cget('command')),
                              state="normal",
                              style=(getattr(button, 'original_style', '') or 'TButton'))
            except Exception:
                pass
            return

        def task_wrapper():
            try:
                runner(should_stop)
            finally:
                try:
                    self.app.unregister_task(key)
                except Exception:
                    pass

        wrapper = TaskUtils.create_task_wrapper(self, button, stop_attr, task_wrapper)
        self.app.workers[self.serial].submit(wrapper)

    def _stop_task(self, stop_attr: str, button: ttk.Button):
        stop_event = getattr(self, stop_attr, None)
        if stop_event is not None:
            TaskUtils.stop_task(stop_event, button)

    def _read_debug_options(self):
        if not hasattr(self, "debug_enable_var") or not self.debug_enable_var.get():
            return None, False
        verbose = bool(self.debug_verbose_var.get())
        raw = (self.debug_threshold_var.get() or "").strip()
        if not raw:
            return matcher.THRESH, verbose
        try:
            value = float(raw)
            if not (0 < value <= 1):
                raise ValueError
        except ValueError:
            self._toast("阈值无效，已回退默认值")
            value = matcher.THRESH
            self.debug_threshold_var.set(f"{value:.2f}")
        return value, verbose

    def _sync_debug_state(self):
        state = "normal" if getattr(self, "debug_enable_var", None) and self.debug_enable_var.get() else "disabled"
        if getattr(self, "debug_verbose_cb", None):
            self.debug_verbose_cb.configure(state=state)
        if getattr(self, "debug_threshold_entry", None):
            self.debug_threshold_entry.configure(state=state)

    # ---------------- 小工具：获取坐标 ----------------
    def _update_outing_mode(self):
        mode = getattr(self, "outing_mode_var", None)
        if mode is None:
            return
        value = mode.get()
        if value == "army":
            if hasattr(self, "fort_panel"):
                self.fort_panel.grid_remove()
            if hasattr(self, "army_panel") and not self.army_panel.winfo_ismapped():
                self.army_panel.grid()
        else:
            if hasattr(self, "army_panel"):
                self.army_panel.grid_remove()
            if hasattr(self, "fort_panel") and not self.fort_panel.winfo_ismapped():
                self.fort_panel.grid()

        if hasattr(self, "outing_btn"):
            if "停止" not in self.outing_btn.cget("text"):
                label = "开始刷全军" if value == "army" else "开始王城/炮台"
                self.outing_btn.config(text=label)
                self.outing_btn.original_text = label

    def _btn_outing(self):
        if getattr(self, "outing_mode_var", None) and self.outing_mode_var.get() == "army":
            self._btn_sweep_army()
        else:
            self._btn_sweep_fort()



    # ---------------- 小工具：启动裁剪/匹配工具 ----------------
    def _btn_launch_cropper(self):
        launch_ui_cropper(toast=self._toast, device_log=self.device_log)

    # ---------------- 小工具：智能选兵 ----------------
    def _btn_smart_troop_selection(self):
        """智能选兵按钮点击处理：开始或停止"""
        if self.smart_troop_running:
            self._stop_smart_troop_selection()
        else:
            self._start_smart_troop_selection()

    def _start_smart_troop_selection(self):
        """开始智能选兵任务"""
        if not matcher.has_cv():
            self._toast("需要依赖：opencv-python 与 numpy。请运行：pip install opencv-python numpy")
            self.device_log("❌ 缺少必要依赖，任务终止")
            return

        if self.serial not in self.app.workers:
            self._toast("设备未连接")
            self.device_log("❌ 设备未连接，任务终止")
            return

        # 更新按钮状态
        self.smart_troop_running = True
        self.smart_troop_stop_flag = False
        self.smart_troop_btn.config(text="停止选兵", style="Accent.TButton")

        # 启动异步任务
        self.smart_troop_thread = threading.Thread(target=self._run_smart_troop_selection_async, daemon=True)
        self.smart_troop_thread.start()

    def _stop_smart_troop_selection(self):
        """停止智能选兵任务"""
        self.smart_troop_stop_flag = True
        self.device_log("⏹️ 用户请求停止智能选兵任务...")
        self._toast("正在停止智能选兵...")

    def _run_smart_troop_selection_async(self):
        """异步执行智能选兵任务"""
        try:
            # 在UI线程中更新日志
            self.after(0, lambda: self.device_log("=" * 50))
            self.after(0, lambda: self.device_log("🎯 开始智能选兵任务"))
            self.after(0, lambda: self.device_log("📋 任务目标：优先选择盾兵和矛兵，避免选择射手"))
            self.after(0, lambda: self.device_log("=" * 50))

            device_worker = self.app.workers[self.serial]

            # 检查设备状态
            self.after(0, lambda: self.device_log("🔍 检查设备连接状态..."))
            time.sleep(0.5)  # 添加延迟让用户看到日志

            if self.smart_troop_stop_flag:
                self._finish_smart_troop_selection("⏹️ 智能选兵任务已被用户停止")
                return

            self.after(0, lambda: self.device_log("✅ 设备连接正常"))
            self.after(0, lambda: self.device_log("🚀 启动智能选兵算法..."))
            time.sleep(0.5)  # 添加延迟

            if self.smart_troop_stop_flag:
                self._finish_smart_troop_selection("⏹️ 智能选兵任务已被用户停止")
                return

            # 运行智能选兵任务（带停止检查的版本）
            success = self._run_new_troop_selection_with_stop_check(device_worker)

            if self.smart_troop_stop_flag:
                self._finish_smart_troop_selection("⏹️ 智能选兵任务已被用户停止")
                return

            if success:
                self.after(0, lambda: self.device_log("=" * 50))
                self.after(0, lambda: self.device_log("🎉 智能选兵任务完成！"))
                self.after(0, lambda: self.device_log("✅ 已优先选择盾兵和矛兵"))
                self.after(0, lambda: self.device_log("🚫 已避免选择射手"))
                self.after(0, lambda: self.device_log("=" * 50))
                self.after(0, lambda: self._toast("智能选兵完成"))
            else:
                self.after(0, lambda: self.device_log("=" * 50))
                self.after(0, lambda: self.device_log("❌ 智能选兵任务失败"))
                self.after(0, lambda: self.device_log("💡 请检查是否在正确的出征界面"))
                self.after(0, lambda: self.device_log("💡 请确保已截取兵种图标模板"))
                self.after(0, lambda: self.device_log("=" * 50))
                self.after(0, lambda: self._toast("智能选兵失败，请查看日志"))

        except Exception as e:
            error_msg = f"❌ 智能选兵任务异常: {str(e)}"
            toast_msg = f"智能选兵异常: {str(e)}"
            self.after(0, lambda: self.device_log("=" * 50))
            self.after(0, lambda: self.device_log(error_msg))
            self.after(0, lambda: self.device_log("💡 请检查错误信息并重试"))
            self.after(0, lambda: self.device_log("=" * 50))
            self.after(0, lambda: self._toast(toast_msg))
        finally:
            # 恢复按钮状态
            self._finish_smart_troop_selection()

    def _finish_smart_troop_selection(self, final_message=None):
        """完成智能选兵任务，恢复按钮状态"""
        def update_ui():
            self.smart_troop_running = False
            self.smart_troop_stop_flag = False
            self.smart_troop_btn.config(text="智能选兵", style="TButton")
            if final_message:
                self.device_log(final_message)

        self.after(0, update_ui)

    # ---------------- 小工具：初始化到野外（已移至小工具） ----------------
    def _btn_init_to_wild(self):
        if not matcher.has_cv():
            self._toast("需要依赖：opencv-python 与 numpy。请运行：pip install opencv-python numpy")
            return
        def submit_one(tab):
            if tab.serial not in self.app.workers:
                return
            self.app.workers[tab.serial].submit(
                lambda t=tab: run_init_to_wild(self.app, t.serial, toast=t._toast, log=t.device_log)
            )
        # 全局操作模式：对所有在线设备执行；否则仅当前标签
        self._for_each_target_tab(submit_one)

    # ---------------- 刷王城/炮台：开始/停止（无公告，直接开始） ----------------
    def _btn_sweep_fort(self):
        mode = self.fort_mode.get()  # "fort" or "city"
        secs = TaskUtils.read_int_param(self.fort_seconds.get(), 8)
        loops = TaskUtils.read_int_param(self.fort_loops.get(), 1)
        step_delay = TaskUtils.read_float_param(self.fort_step_delay.get(), 0.10)

        debug_threshold, debug_verbose = self._read_debug_options()

        def runner(should_stop):
            run_sweep_fort(
                self.app, self.serial, secs, mode,
                toast=self._toast, log=self.device_log,
                loop_count=loops,
                should_stop=should_stop,
                step_delay=step_delay,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )

        self._start_task_with_button("fort", self.outing_btn, runner)
        # 全局模式：其他设备并行执行
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self or tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_sweep_fort(
                        self.app, t.serial, secs, mode,
                        toast=t._toast, log=t.device_log,
                        loop_count=loops,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        step_delay=step_delay,
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _btn_sweep_army(self):
        # 读取参数
        secs = TaskUtils.read_int_param(self.sweep_seconds.get(), 8)
        loops = TaskUtils.read_int_param(self.sweep_loops.get(), 1)
        total_secs = TaskUtils.read_int_param(self.sweep_total.get(), 0)
        step_delay = TaskUtils.read_float_param(self.sweep_step_delay.get(), 0.10)

        # 公告（10s 自动或手动开始）
        self._show_sweep_notice(lambda: self._start_sweep_task(secs, loops, total_secs, step_delay))
    # ---------------- 打熊模式 ----------------
    def _btn_bear_mode(self):
        debug_threshold, debug_verbose = self._read_debug_options()
        time_raw = (self.bear_time_var.get() or "").strip()
        if len(time_raw) != 6 or not time_raw.isdigit():
            self._toast("打熊时间需为六位数字（HHMMSS），例如 203000")
            return
        hour = int(time_raw[0:2])
        minute = int(time_raw[2:4])
        second = int(time_raw[4:6])
        try:
            target_time = _dt.time(hour=hour, minute=minute, second=second)
        except ValueError:
            self._toast("打熊时间超出有效范围")
            return
        day_mode = self.bear_day_mode_map.get(self.bear_day_mode_var.get(), "both")
        head_mode = self.bear_head_mode_map.get(self.bear_head_mode_var.get(), "random")
        interval = TaskUtils.read_int_param(self.bear_interval_var.get(), 300)
        if interval <= 0:
            self._toast("发车间隔须为正整数秒")
            return
        options = BearOptions(
            target_time=target_time,
            day_mode=day_mode,
            send_car=bool(self.bear_send_car_var.get()),
            head_mode=head_mode,
            interval_sec=interval,
        )
        self._save_bear_defaults(options, time_raw)

        def runner(should_stop):
            run_bear_mode(
                self.app, self.serial,
                toast=self._toast,
                log=self.device_log,
                should_stop=should_stop,
                options=options,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )

        self._start_task_with_button("bear_mode", self.bear_btn, runner)

        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self or tab.serial not in self.app.workers:
                    continue
                opts = BearOptions(
                    target_time=options.target_time,
                    day_mode=options.day_mode,
                    send_car=options.send_car,
                    head_mode=options.head_mode,
                    interval_sec=options.interval_sec,
                )
                self.app.workers[tab.serial].submit(
                    lambda t=tab, o=opts: run_bear_mode(
                        self.app, t.serial,
                        toast=t._toast,
                        log=t.device_log,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        options=o,
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _load_bear_defaults(self):
        try:
            cfg = getattr(self.app, "cfg", {}) or {}
            opts = (cfg.get("bear_options", {}) or {}).get(self.serial)
            if not opts:
                return

            time_val = str(opts.get("time", "")).strip()
            if time_val:
                if time_val.isdigit() and len(time_val) < 6:
                    time_val = time_val.zfill(6)
                self.bear_time_var.set(time_val)

            day_label = opts.get("day_mode_label")
            day_code = opts.get("day_mode")
            if day_label in self.bear_day_mode_map:
                self.bear_day_mode_var.set(day_label)
            elif day_code:
                for label, code in self.bear_day_mode_map.items():
                    if code == day_code:
                        self.bear_day_mode_var.set(label)
                        break

            send_val = opts.get("send_car")
            if send_val is not None:
                if isinstance(send_val, str):
                    send_bool = send_val.lower() in ("1", "true", "yes", "on")
                else:
                    send_bool = bool(send_val)
                self.bear_send_car_var.set(send_bool)

            head_label = opts.get("head_mode_label")
            head_code = opts.get("head_mode")
            if head_label in self.bear_head_mode_map:
                self.bear_head_mode_var.set(head_label)
            elif head_code:
                for label, code in self.bear_head_mode_map.items():
                    if code == head_code:
                        self.bear_head_mode_var.set(label)
                        break

            interval = str(opts.get("interval", "")).strip()
            if interval:
                self.bear_interval_var.set(interval)
        except Exception:
            pass

    def _save_bear_defaults(self, options: BearOptions, time_raw: str):
        try:
            cfg = getattr(self.app, "cfg", {}) or {}
            cfg.setdefault("bear_options", {})
            cfg["bear_options"][self.serial] = {
                "time": time_raw,
                "day_mode_label": self.bear_day_mode_var.get(),
                "day_mode": options.day_mode,
                "send_car": bool(self.bear_send_car_var.get()),
                "head_mode_label": self.bear_head_mode_var.get(),
                "head_mode": options.head_mode,
                "interval": str(options.interval_sec),
            }
            self.app.config_mgr.save(cfg)
            self.app.cfg = cfg
        except Exception:
            pass

    # ---------------- 秒进集结 ----------------
    def _btn_fast_join(self):
        debug_threshold, debug_verbose = self._read_debug_options()
        def runner(should_stop):
            run_fast_join_rally(
                self.app, self.serial,
                toast=self._toast,
                log=self.device_log,
                should_stop=should_stop,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )
        # 当前标签：带按钮可停止
        self._start_task_with_button("fast_join", self.fast_join_btn, runner)
        # 全局模式下：其他设备并行执行（无按钮绑定）
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self:
                    continue
                if tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_fast_join_rally(
                        self.app, t.serial,
                        toast=t._toast,
                        log=t.device_log,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    # ---------------- 一键四阶 ----------------
    def _btn_promote_rank4(self):
        debug_threshold, debug_verbose = self._read_debug_options()
        def runner(should_stop):
            run_promote_rank4(
                self.app, self.serial,
                toast=self._toast,
                log=self.device_log,
                should_stop=should_stop,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )
        # 当前标签：带按钮可停止
        self._start_task_with_button("promote_rank4", self.promote_rank4_btn, runner)
        # 全局模式：其他设备并行执行（无按钮绑定）
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self:
                    continue
                if tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_promote_rank4(
                        self.app, t.serial,
                        toast=t._toast,
                        log=t.device_log,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )


    def _start_sweep_task(self, secs: int, loops: int, total_secs: int, step_delay: float):
        debug_threshold, debug_verbose = self._read_debug_options()

        def runner(should_stop):
            run_sweep_army(
                self.app, self.serial, secs,
                toast=self._toast, log=self.device_log,
                loop_count=loops,
                total_duration=total_secs,
                should_stop=should_stop,
                step_delay=step_delay,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )

        self._start_task_with_button("sweep", self.outing_btn, runner)
        # 全局模式：其他设备并行执行
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self or tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_sweep_army(
                        self.app, t.serial, secs,
                        toast=t._toast, log=t.device_log,
                        loop_count=loops,
                        total_duration=total_secs,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        step_delay=step_delay,
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _btn_emergency_heal(self):
        if not matcher.has_cv():
            self._toast("需要依赖：opencv-python 和 numpy。请运行：pip install opencv-python numpy")
            return
        debug_threshold, debug_verbose = self._read_debug_options()

        def runner(should_stop):
            run_emergency_heal(
                self.app, self.serial,
                toast=self._toast, log=self.device_log,
                should_stop=should_stop,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )

        self._start_task_with_button("emergency_heal", self.emergency_heal_btn, runner)
        # 全局模式：其他设备并行执行
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self or tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_emergency_heal(
                        self.app, t.serial,
                        toast=t._toast, log=t.device_log,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _btn_sweep_hunt(self):
        hunt_type = self.hunt_type.get()  # "beast" or "monster"
        loops = TaskUtils.read_int_param(self.hunt_loops.get(), 1)
        step_delay = TaskUtils.read_float_param(self.hunt_step_delay.get(), 0.10)

        beast_levels = []
        if self.beast_30_var.get():
            beast_levels.append(30)
        if self.beast_26_var.get():
            beast_levels.append(26)

        monster_levels = []
        if self.monster_8_var.get():
            monster_levels.append(8)
        if self.monster_7_var.get():
            monster_levels.append(7)
        if self.monster_6_var.get():
            monster_levels.append(6)
        if self.monster_5_var.get():
            monster_levels.append(5)

        selected_teams = []
        for team_num, var in self.team_vars.items():
            if var.get():
                selected_teams.append(team_num)

        if hunt_type == "beast" and not beast_levels:
            self._toast("请至少选择一个野兽级别")
            return
        elif hunt_type == "monster" and not monster_levels:
            self._toast("请至少选择一个巨兽级别")
            return

        if not selected_teams:
            self._toast("请至少选择一个编队")
            return

        debug_threshold, debug_verbose = self._read_debug_options()

        def runner(should_stop):
            run_sweep_hunt(
                self.app, self.serial, hunt_type,
                beast_levels=beast_levels,
                monster_levels=monster_levels,
                selected_teams=selected_teams,
                toast=self._toast, log=self.device_log,
                loop_count=loops,
                should_stop=should_stop,
                step_delay=step_delay,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )

        self._start_task_with_button("hunt", self.hunt_btn, runner)
        # 全局模式：其他设备并行执行
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self or tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_sweep_hunt(
                        self.app, t.serial, hunt_type,
                        beast_levels=beast_levels,
                        monster_levels=monster_levels,
                        selected_teams=selected_teams,
                        toast=t._toast, log=t.device_log,
                        loop_count=loops,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        step_delay=step_delay,
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _btn_withdraw_troops(self):
        if not matcher.has_cv():
            self._toast("需要依赖：opencv-python 和 numpy。请运行：pip install opencv-python numpy")
            return
        debug_threshold, debug_verbose = self._read_debug_options()
        def runner(should_stop):
            run_withdraw_troops(
                self.app, self.serial,
                toast=self._toast, log=self.device_log,
                should_stop=should_stop,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )
        # 当前标签：带按钮可停止
        self._start_task_with_button("withdraw", self.withdraw_btn, runner)
        # 全局模式下：其他设备并行执行（无按钮绑定）
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self:
                    continue
                if tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_withdraw_troops(
                        self.app, t.serial,
                        toast=t._toast, log=t.device_log,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _btn_auto_garrison(self):
        if not matcher.has_cv():
            self._toast("需要依赖：opencv-python 和 numpy。请运行：pip install opencv-python numpy")
            return
        raw_mode = getattr(self, "garrison_mode_var", None).get() if hasattr(self, "garrison_mode_var") else ""
        mode = "joy" if raw_mode in ("乔伊", "joy") else "harvest"
        debug_threshold, debug_verbose = self._read_debug_options()

        # 全局模式：用“协调器”统一启动并等待所有设备完成后再结束按钮
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            stop_attr = "_garrison_all_stop_ev"
            stop_event = TaskUtils.create_stop_event()
            setattr(self, stop_attr, stop_event)

            def should_stop_all():
                # 按钮停止或全局紧急停止
                return stop_event.is_set() or bool(getattr(self.app, "_force_stop_all", False))

            def coordinator_wrapper():
                try:
                    # 注册协调器任务，保证停止优先级
                    key = f"garrison:ALL"
                    try:
                        self.app.register_task(key, stop_event, resume_cb=None, button=self.garrison_btn)
                    except Exception:
                        pass

                    # 提交所有设备的驻军任务（共享 should_stop）
                    futures = []
                    for tab in self.app.device_tabs.values():
                        if tab.serial not in self.app.workers:
                            continue
                        def run_one(t=tab):
                            run_auto_garrison(
                                self.app, t.serial, mode,
                                toast=t._toast, log=t.device_log,
                                should_stop=should_stop_all,
                                threshold=debug_threshold,
                                verbose=debug_verbose,
                            )
                        futures.append(self.app.workers[tab.serial].submit(run_one))

                    # 等待全部完成或收到停止
                    while True:
                        if should_stop_all():
                            break
                        done = all(f.done() for f in futures)
                        if done:
                            break
                        time.sleep(0.2)
                finally:
                    try:
                        self.app.unregister_task("garrison:ALL")
                    except Exception:
                        pass

            wrapper = TaskUtils.create_task_wrapper(self, self.garrison_btn, stop_attr, coordinator_wrapper)
            self.app.workers.get(self.serial, self.app.workers[next(iter(self.app.workers), None)]).submit(wrapper)
            return

        # 单设备：保持原逻辑
        def runner(should_stop):
            run_auto_garrison(
                self.app, self.serial, mode,
                toast=self._toast, log=self.device_log,
                should_stop=should_stop,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )
        self._start_task_with_button("garrison", self.garrison_btn, runner)

    def _btn_ranshuang(self):
        """燃霜模式"""
        if not matcher.has_cv():
            self._toast("需要依赖：opencv-python 和 numpy。请运行：pip install opencv-python numpy")
            return
        debug_threshold, debug_verbose = self._read_debug_options()

        from .tasks.ranshuang_mode import run_ranshuang_mode

        def runner(should_stop):
            run_ranshuang_mode(
                self.app, self.serial,
                toast=self._toast, log=self.device_log,
                should_stop=should_stop,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )

        self._start_task_with_button("ranshuang", self.ranshuang_btn, runner)
        # 全局模式：其他设备并行执行
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self or tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_ranshuang_mode(
                        self.app, t.serial,
                        toast=t._toast, log=t.device_log,
                        should_stop=lambda: bool(getattr(self.app, "_force_stop_all", False)),
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _btn_close_alliance_help(self):
        debug_threshold, debug_verbose = self._read_debug_options()
        def submit_one(tab):
            if tab.serial not in self.app.workers:
                return
            self.app.workers[tab.serial].submit(
                lambda: run_close_alliance_help(
                    self.app, tab.serial, toast=tab._toast, log=tab.device_log,
                    threshold=debug_threshold, verbose=debug_verbose
                )
            )
        self._for_each_target_tab(submit_one)

    def _btn_open_alliance_help(self):
        debug_threshold, debug_verbose = self._read_debug_options()
        def submit_one(tab):
            if tab.serial not in self.app.workers:
                return
            self.app.workers[tab.serial].submit(
                lambda: run_open_alliance_help(
                    self.app, tab.serial, toast=tab._toast, log=tab.device_log,
                    threshold=debug_threshold, verbose=debug_verbose
                )
            )
        self._for_each_target_tab(submit_one)

    def _btn_auto_like(self):
        if not matcher.has_cv():
            self._toast("需要依赖：opencv-python 和 numpy。请运行：pip install opencv-python numpy")
            return
        debug_threshold, debug_verbose = self._read_debug_options()
        # 当前标签：带按钮可停止
        def runner(should_stop):
            run_auto_like(
                self.app, self.serial,
                toast=self._toast, log=self.device_log,
                should_stop=should_stop,
                threshold=debug_threshold,
                verbose=debug_verbose,
            )
        # 切换按钮为“停止点赞”
        self._start_task_with_button("auto_like", self.auto_like_btn, runner)
        # 全局模式下：其他设备并行执行（无按钮绑定）
        if getattr(self.app, "is_global_multi_mode", None) and self.app.is_global_multi_mode():
            for tab in self.app.device_tabs.values():
                if tab is self:
                    continue
                if tab.serial not in self.app.workers:
                    continue
                self.app.workers[tab.serial].submit(
                    lambda t=tab: run_auto_like(
                        self.app, t.serial,
                        toast=t._toast, log=t.device_log,
                        should_stop=lambda: False,
                        threshold=debug_threshold,
                        verbose=debug_verbose,
                    )
                )

    def _run_new_troop_selection_with_stop_check(self, device_worker):
        """运行智能选兵任务，支持停止检查和步骤延迟"""
        from ..tasks.new_troop_selection import NewTroopSelector

        try:
            self.after(0, lambda: self.device_log("🎯 启动新版智能选兵系统..."))

            # 检查依赖
            if not matcher.has_cv():
                self.after(0, lambda: self.device_log("❌ 缺少OpenCV依赖"))
                return False

            # 创建选择器
            selector = NewTroopSelector(device_worker, self._thread_safe_log)

            # 加载模板
            self.after(0, lambda: self.device_log("📂 正在加载兵种识别模板..."))
            time.sleep(0)

            if self.smart_troop_stop_flag:
                return False

            if not selector.load_templates():
                self.after(0, lambda: self.device_log("❌ 模板加载失败，任务终止"))
                return False

            time.sleep(0)

            if self.smart_troop_stop_flag:
                return False

            # 执行选兵流程，每个步骤都检查停止标志
            return self._execute_selection_with_stop_check(selector)

        except Exception as e:
            error_msg = f"❌ 新版智能选兵异常: {str(e)}"
            self.after(0, lambda: self.device_log(error_msg))
            return False

    def _execute_selection_with_stop_check(self, selector):
        """执行选兵流程：委派给 selector.run_troop_selection()（包含初始+2次拖动）"""
        try:
            self.after(0, lambda: self.device_log("🎯 开始执行新版智能选兵流程（自动三轮：初始+2次拖动）..."))
            self.after(0, lambda: self.device_log("=" * 50))
            time.sleep(0)

            if self.smart_troop_stop_flag:
                return False

            # 直接运行选择器内置流程（含拖动与多轮扫描）
            result = selector.run_troop_selection()

            self.after(0, lambda: self.device_log("=" * 50))
            if result:
                self.after(0, lambda: self.device_log("🎉 智能选兵流程执行完成！"))
            else:
                self.after(0, lambda: self.device_log("❌ 智能选兵流程失败"))
            return result

        except Exception as e:
            error_msg = f"❌ 执行选兵流程异常: {str(e)}"
            self.after(0, lambda: self.device_log(error_msg))
            return False

    def _process_shields_with_stop_check(self, selector):
        """处理盾兵选择，支持停止检查"""
        # 这里简化处理，直接调用原方法但添加停止检查
        # 在实际实现中，需要修改selector的方法来支持停止检查
        try:
            return selector.step3_process_shields()
        except Exception as e:
            error_msg = f"❌ 处理盾兵异常: {str(e)}"
            self.after(0, lambda: self.device_log(error_msg))
            return False

    def _process_spears_with_stop_check(self, selector):
        """处理矛兵选择，支持停止检查"""
        # 这里简化处理，直接调用原方法但添加停止检查
        # 在实际实现中，需要修改selector的方法来支持停止检查
        try:
            return selector.step4_process_spears()
        except Exception as e:
            error_msg = f"❌ 处理矛兵异常: {str(e)}"
            self.after(0, lambda: self.device_log(error_msg))
            return False

    def _thread_safe_log(self, message, level="INFO"):
        """线程安全的日志记录方法"""
        # 仅传递 message，避免因不同签名导致的异常
        self.after(0, lambda: self.device_log(message))

    def _show_sweep_notice(self, on_start):
        """
        刷前注意事项公告：10 秒自动开始，也可手动“我已确认，开始”
        on_start: 无参回调，用户确认或倒计时结束后调用
        """
        root = self.winfo_toplevel()
        top = tk.Toplevel(root)
        top.title("提示")
        top.attributes("-topmost", True)

        # 尽量居中
        try:
            root.update_idletasks()
            w, h = 560, 380
            x = root.winfo_rootx() + (root.winfo_width() - w) // 2
            y = root.winfo_rooty() + (root.winfo_height() - h) // 3
            top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        except Exception:
            top.geometry("560x380+200+160")

        text = (
            "开始前请确认：\n"
            "1）编队“4号队”可出击（已整备且非驻防）。\n"
            "2）目标已加入【收藏】，且置于【敌人】列表第一个。\n"
            "3）至少先手动出征一次，确保有伤兵（用于后续治疗校验）。\n"
            "4）【治疗时长 × 一次治疗人数】≥ 一次战斗伤兵数量，避免爆医院。\n"
            "5）确保网络与设备稳定，期间可能触发多次连续点击。\n"
        )

        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, height=12, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("end", text)
        txt.config(state="disabled")

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(8, 0))

        self._sweep_cd = 10
        cd_var = tk.StringVar(value=f"（自动开始倒计时：{self._sweep_cd}s）")

        def tick():
            self._sweep_cd -= 1
            if self._sweep_cd <= 0:
                try:
                    top.destroy()
                except Exception:
                    pass
                on_start()
            else:
                cd_var.set(f"（自动开始倒计时：{self._sweep_cd}s）")
                top.after(1000, tick)

        ttk.Button(btn_row, text="我已确认，开始",
                   command=lambda: (top.destroy(), on_start())).pack(side="left")
        ttk.Label(btn_row, textvariable=cd_var).pack(side="right")
        top.after(1000, tick)

    # ---------------- 打资源（危险：仅当前设备） ----------------
    def _btn_edit_attack_coords(self):
        root = self.winfo_toplevel()
        top = tk.Toplevel(root)
        top.title("编辑资源坐标（每行：x:y:备注名:攻击轮次）")
        top.attributes("-topmost", True)
        frm = ttk.Frame(top, padding=8)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, width=48, height=12)
        txt.pack(fill="both", expand=True)
        try:
            txt.insert("end", self.attack_coords_text)
        except Exception:
            pass
        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(8,0))
        def _save():
            try:
                self.attack_coords_text = txt.get("1.0", "end").strip()
            except Exception:
                self.attack_coords_text = ""
            # 持久化到配置
            try:
                cfg = getattr(self.app, "cfg", {}) or {}
                cfg.setdefault("attack_coords", {})
                cfg["attack_coords"][self.serial] = self.attack_coords_text
                self.app.config_mgr.save(cfg)
                self.app.cfg = cfg
            except Exception:
                pass
            try:
                top.destroy()
            except Exception:
                pass
            self._toast("已保存资源坐标（已持久化）")
        ttk.Button(btn_row, text="保存", command=_save).pack(side=tk.RIGHT)

    def _btn_attack_resources(self):
        # 危险：即使全局模式勾选，也仅操作当前设备
        from .tasks.attack_resources import parse_coords_text, run_attack_resources
        coords = parse_coords_text(getattr(self, "attack_coords_text", ""))
        if not coords:
            self._toast("请先点击‘编辑资源坐标’并填写坐标\n每行：x:y:备注名:攻击轮次")
            return
        # 设备标签备注名
        remark = None
        try:
            cfg = getattr(self.app, "cfg", {}) or {}
            remark = (getattr(cfg, "get", None) and cfg.get("notes", {}).get(self.serial)) or None
        except Exception:
            remark = None
        if not remark:
            remark = self.serial
        # 列出备注名
        names = [n for (_, _, n, _) in coords]
        # 确认弹窗（无倒计时）
        root = self.winfo_toplevel()
        top = tk.Toplevel(root)
        top.title("确认：打资源（危险操作）")
        top.attributes("-topmost", True)
        try:
            root.update_idletasks()
            w, h = 520, 380
            x = root.winfo_rootx() + (root.winfo_width() - w) // 2
            y = root.winfo_rooty() + (root.winfo_height() - h) // 3
            top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        except Exception:
            top.geometry("520x380+200+160")
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        msg = (
            f"将对‘{remark}’设备执行‘打资源’（仅当前设备，不受全局模式控制）。\n"
            "以下为输入的所有备注名：\n  - " + "\n  - ".join(names)
        )
        lab = tk.Text(frm, height=10, wrap="word")
        lab.pack(fill="both", expand=True)
        lab.insert("end", msg)
        lab.config(state="disabled")
        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(8,0))
        def _start():
            try:
                top.destroy()
            except Exception:
                pass
            # 读取调试选项
            debug_threshold, debug_verbose = self._read_debug_options()
            def runner(should_stop):
                # 从组合框读取中文显示 -> 转为英文代码；若失败则使用配置中的代码
                try:
                    sel_label = self.attack_timeout_action_var.get()
                    on_timeout = self.attack_timeout_reverse_map.get(sel_label, self.app.cfg.get("attack_on_timeout", "continue"))
                except Exception:
                    on_timeout = self.app.cfg.get("attack_on_timeout", "continue")
                run_attack_resources(
                    self.app, self.serial,
                    coords,
                    toast=self._toast, log=self.device_log,
                    should_stop=should_stop,
                    threshold=debug_threshold,
                    verbose=debug_verbose,
                    on_timeout=on_timeout,
                )
            self._start_task_with_button("attack_resources", self.attack_btn, runner)
        ttk.Button(btn_row, text="确认打资源", command=_start).pack(side=tk.RIGHT)
