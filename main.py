import os
import sys

# Switch to Qt-based UI for v1.15
from mumu_adb_controller.ui_qt.app_qt import launch as launch_qt_app


# ---- Windows: hide console by default ----
def _hide_console_by_default() -> None:
    try:
        # Allow override via flag/env
        if "--show-console" in sys.argv[1:] or os.environ.get("SHOW_CONSOLE"):
            return
        if os.name != "nt":
            return
        import ctypes  # type: ignore
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
    except Exception:
        # Never block app launch due to console hiding
        pass


def _launch_main_app() -> None:
    launch_qt_app()


def _launch_tool(tool_name: str) -> None:
    if tool_name == "ui_cropper":
        from mumu_adb_controller.tools.ui_cropper_updated_v2 import main as cropper_main
        cropper_main()
        return
    raise SystemExit(f"Unknown tool: {tool_name}")


def main() -> None:
    # Hide console early (Windows)
    _hide_console_by_default()

    args = [a for a in sys.argv[1:] if a != "--show-console"]
    if len(args) >= 2 and args[0] == "--launch-tool":
        _launch_tool(args[1])
        return
    _launch_main_app()


if __name__ == "__main__":
    main()
