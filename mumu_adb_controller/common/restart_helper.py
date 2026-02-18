#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程重启辅助模块
提供安全的进程停止和重启功能
"""

import os
import sys
import subprocess
import threading
import time
from typing import Optional, List


class RestartHelper:
    """进程重启辅助类"""
    
    @staticmethod
    def get_current_process_info():
        """获取当前进程信息"""
        return {
            "executable": sys.executable,
            "argv": sys.argv.copy(),
            "cwd": os.getcwd(),
            "frozen": getattr(sys, "frozen", False)
        }
    
    @staticmethod
    def kill_all_threads(exclude_main: bool = True) -> int:
        """
        尝试停止所有线程（除了主线程）
        返回活跃线程数量
        """
        count = 0
        try:
            import threading
            for thread in threading.enumerate():
                if exclude_main and thread is threading.main_thread():
                    continue
                # daemon线程会在主线程退出时自动结束
                # 非daemon线程需要等待或强制结束
                if thread.is_alive():
                    count += 1
        except Exception:
            pass
        return count
    
    @staticmethod
    def restart_process(delay: float = 0.5) -> None:
        """
        重启当前进程
        
        Args:
            delay: 延迟多少秒后重启（给当前进程时间清理资源）
        """
        info = RestartHelper.get_current_process_info()
        
        def _restart():
            time.sleep(delay)
            try:
                if info["frozen"]:
                    # 打包后的exe
                    subprocess.Popen([info["executable"]] + info["argv"][1:], cwd=info["cwd"])
                else:
                    # 开发环境
                    subprocess.Popen([info["executable"]] + info["argv"], cwd=info["cwd"])
            except Exception as e:
                print(f"[ERROR] 重启失败: {e}")
        
        # 在后台线程中启动新进程
        restart_thread = threading.Thread(target=_restart, daemon=True)
        restart_thread.start()
    
    @staticmethod
    def force_exit(exit_code: int = 0) -> None:
        """
        强制退出当前进程
        
        Args:
            exit_code: 退出码
        """
        try:
            # 尝试正常退出
            sys.exit(exit_code)
        except Exception:
            # 如果正常退出失败，强制退出
            os._exit(exit_code)
    
    @staticmethod
    def restart_and_exit(delay: float = 0.5, exit_code: int = 0) -> None:
        """
        重启进程并退出当前进程
        
        Args:
            delay: 延迟多少秒后重启
            exit_code: 退出码
        """
        RestartHelper.restart_process(delay)
        time.sleep(delay + 0.1)  # 确保重启线程已启动
        RestartHelper.force_exit(exit_code)


class ProcessCleaner:
    """进程清理器"""
    
    def __init__(self, logger=None):
        self.logger = logger
        self._cleanup_callbacks: List[callable] = []
    
    def add_cleanup_callback(self, callback: callable) -> None:
        """添加清理回调函数"""
        self._cleanup_callbacks.append(callback)
    
    def log(self, msg: str) -> None:
        """记录日志"""
        if self.logger:
            try:
                self.logger.info(msg)
            except Exception:
                pass
        print(msg)
    
    def cleanup_all(self) -> None:
        """执行所有清理操作"""
        self.log("[清理] 开始清理所有资源...")
        
        # 1. 执行自定义清理回调
        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                self.log(f"[清理] 清理回调失败: {e}")
        
        # 2. 统计活跃线程
        thread_count = RestartHelper.kill_all_threads(exclude_main=True)
        self.log(f"[清理] 当前活跃线程数: {thread_count}")
        
        # 3. 等待一小段时间让线程自然结束
        time.sleep(0.3)
        
        self.log("[清理] 清理完成")
    
    def stop_and_restart(self, delay: float = 0.5) -> None:
        """
        停止所有任务并重启程序
        
        Args:
            delay: 延迟多少秒后重启
        """
        self.log("[重启] 准备停止所有任务并重启程序...")
        
        # 1. 清理资源
        self.cleanup_all()
        
        # 2. 重启进程
        self.log("[重启] 正在重启程序...")
        RestartHelper.restart_and_exit(delay)


# 全局清理器实例（可选）
_global_cleaner: Optional[ProcessCleaner] = None


def get_global_cleaner(logger=None) -> ProcessCleaner:
    """获取全局清理器实例"""
    global _global_cleaner
    if _global_cleaner is None:
        _global_cleaner = ProcessCleaner(logger)
    return _global_cleaner


def stop_and_restart_app(logger=None, delay: float = 0.5) -> None:
    """
    停止所有任务并重启应用程序（便捷函数）
    
    Args:
        logger: 日志记录器
        delay: 延迟多少秒后重启
    """
    cleaner = get_global_cleaner(logger)
    cleaner.stop_and_restart(delay)

