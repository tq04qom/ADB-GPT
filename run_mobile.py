#!/usr/bin/env python3
"""
移动端界面启动脚本
运行方式：python run_mobile.py
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from mumu_adb_controller.ui_qt.mobile_view_qt_new import MobileMainWindow
from mumu_adb_controller.core.adb import AdbClient
from mumu_adb_controller.common.logger import Logger
from mumu_adb_controller.common.worker import DeviceWorker
from mumu_adb_controller.common.config import AppConfig


class MobileApp:
    """移动端应用"""

    def __init__(self):
        # 配置管理器
        self.config_mgr = AppConfig(app_name="MuMuADBController")
        self.cfg = self.config_mgr.load() or {}

        # 日志
        self.logger = Logger()

        # ADB客户端
        self.adb = AdbClient(adb_path=self.cfg.get("adb_path"), logger=self.logger)

        # 设备Worker字典
        self.workers = {}

        # 设备标签页字典（移动端需要）
        self.device_tabs = {}

        # 窗口引用（用于置顶功能）
        self.window = None

        # 初始化设备
        self._init_devices()
    
    def _init_devices(self):
        """初始化设备"""
        # 获取所有设备
        devices = self.adb.list_devices()
        if not devices:
            print("未检测到设备")
            return

        # 为每个设备创建Worker
        for serial in devices:
            worker = DeviceWorker(serial, self.adb, self.logger)
            worker.start()
            self.workers[serial] = worker
            print(f"已初始化设备: {serial}")
    
    def append_device_log(self, serial: str, msg: str):
        """设备日志（移动端不显示）"""
        pass

    def auto_connect_mumu(self):
        """自动连接MuMu模拟器"""
        print("正在扫描MuMu模拟器...")
        # 这里可以添加自动连接逻辑
        # 暂时只是重新初始化设备
        self._init_devices()

    def stop_all_now(self):
        """停止所有任务"""
        print("停止所有任务...")
        for serial, worker in self.workers.items():
            worker.stop_all()
            print(f"已停止设备 {serial} 的所有任务")

    def toggle_always_on_top(self):
        """切换窗口置顶"""
        if self.window is None:
            print("窗口未初始化")
            return

        current_flags = self.window.windowFlags()
        if current_flags & Qt.WindowStaysOnTopHint:
            # 当前是置顶，取消置顶
            self.window.setWindowFlags(current_flags & ~Qt.WindowStaysOnTopHint)
            print("窗口置顶: 关闭")
        else:
            # 当前不是置顶，设置置顶
            self.window.setWindowFlags(current_flags | Qt.WindowStaysOnTopHint)
            print("窗口置顶: 开启")

        # 重新显示窗口（setWindowFlags会隐藏窗口）
        self.window.show()

    def toggle_global_mode(self):
        """切换全局操作模式"""
        current = self.cfg.get("global_mode", False)
        self.cfg["global_mode"] = not current
        self.config_mgr.save(self.cfg)
        print(f"全局操作模式: {'开启' if not current else '关闭'}")


def main():
    """主函数"""
    try:
        print("正在启动移动界面...")
        app = QApplication(sys.argv)

        # 设置应用样式
        app.setStyle("Fusion")
        print("应用样式设置完成")

        # 创建应用实例
        mobile_app = MobileApp()
        print("应用实例创建完成")

        # 创建主窗口
        window = MobileMainWindow(mobile_app)
        mobile_app.window = window  # 保存窗口引用
        print("主窗口创建完成")

        window.show()
        print("窗口显示完成")

        sys.exit(app.exec())
    except Exception as e:
        print(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

