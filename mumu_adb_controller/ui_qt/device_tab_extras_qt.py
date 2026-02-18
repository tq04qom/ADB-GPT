"""
设备页签扩展面板（已拆分到 panels/ 目录）
保留此文件以兼容旧导入，实际实现已迁移到独立模块
"""
from __future__ import annotations

# 向后兼容：导出旧类名
from .panels.base_panel import BasePanel as _BoxBase
from .panels.hunt_panel import HuntPanel as HuntBox
from .panels.bear_panel import BearPanel as BearModeBox
from .panels.alliance_panel_fix import AlliancePanel as AllianceBox
from .panels.tools_panel import ToolsPanel as ToolsBox
from .panels.resources_panel import ResourcesPanel as ResourcesBox

__all__ = [
    "_BoxBase",
    "HuntBox",
    "BearModeBox",
    "AllianceBox",
    "ToolsBox",
    "ResourcesBox",
]
