# mumu_adb_controller/ui/helpers/tool_launcher.py
import os
import sys
import subprocess
from typing import Optional

# Frozen-safe path: prioritize centralized management; provide fallback on failure
try:
    from mumu_adb_controller.common.pathutil import res_path
except Exception:  # fallback
    def _app_base_dir() -> str:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    def res_path(*parts: str) -> str:
        return os.path.join(_app_base_dir(), *parts)


def _candidate_roots():
    """Keep your original root directory guessing logic; as a backup for res_path."""
    cand = set()
    try:
        cand.add(os.path.abspath(os.getcwd()))
    except Exception:
        pass
    try:
        import __main__
        if hasattr(__main__, "__file__"):
            cand.add(os.path.abspath(os.path.dirname(__main__.__file__)))
    except Exception:
        pass
    try:
        here = os.path.abspath(os.path.dirname(__file__))  # .../ui/helpers/
        cand.add(os.path.abspath(os.path.join(here, "..", "..")))  # project root
    except Exception:
        pass
    try:
        cand.add(os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..")))
    except Exception:
        pass
    # bubble up
    for root in list(cand):
        p = root
        for _ in range(5):
            cand.add(p)
            p = os.path.abspath(os.path.join(p, ".."))
    return list(cand)


def _find_by_res_path() -> Optional[str]:
    """Priority: use frozen-safe resource location to find tools/ui_cropper_updated_v2.py"""
    p = res_path("tools", "ui_cropper_updated_v2.py")
    return p if os.path.isfile(p) else None


def _find_by_candidates() -> Optional[str]:
    """Fallback: search for tools/ui_cropper_updated_v2.py or tool/ui_cropper_updated_v2.py in candidate root directories"""
    names = [
        os.path.join("tools", "ui_cropper_updated_v2.py"),
        os.path.join("tool", "ui_cropper_updated_v2.py"),
    ]
    for root in _candidate_roots():
        for n in names:
            p = os.path.join(root, n)
            if os.path.isfile(p):
                return p
    return None


def _find_by_module() -> Optional[str]:
    """
    Last fallback: locate file path through module.
    - If source code/unpacked files exist, return its __file__
    - If packaged form doesn't show files but module is executable, use `-m module` startup later.
    """
    try:
        import importlib
        mod = importlib.import_module("mumu_adb_controller.tools.ui_cropper_updated_v2")
        path = getattr(mod, "__file__", None)
        if path and os.path.isfile(path):
            return os.path.abspath(path)
        return None
    except Exception:
        return None


def find_cropper_script() -> Optional[str]:
    """
    Return script path; if physical file not found, return None (use -m startup then).
    Search order: res_path -> candidates -> module.__file__
    """
    return _find_by_res_path() or _find_by_candidates() or _find_by_module()


def _can_run_module() -> bool:
    """Determine if we can start with `-m mumu_adb_controller.tools.ui_cropper_updated_v2`."""
    # In packaged environment, module startup method will cause main program restart, so should be disabled
    if getattr(sys, "frozen", False):
        return False
    
    try:
        import importlib
        importlib.import_module("mumu_adb_controller.tools.ui_cropper_updated_v2")
        return True
    except Exception:
        return False


def launch_ui_cropper(toast, device_log):
    """
    Launch screenshot cropping and matching test tool (ui_cropper_updated_v2.py)
    - Priority: start directly with script path;
    - If script not found, and module is importable, use `-m module` startup;
    - Hide black window on Windows.
    toast: callable(str) -> None
    device_log: callable(str) -> None
    """
    script_path = find_cropper_script()
    python = sys.executable or "python"
    is_frozen = getattr(sys, "frozen", False)

    # Windows: hide console window
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    try:
        # In packaged environment, always use --launch-tool parameter
        if is_frozen:
            if device_log:
                device_log(f"[DEBUG] Launching tool in packaged mode: {sys.executable} --launch-tool ui_cropper")

            # Launch tool with hidden console
            proc = subprocess.Popen(
                [sys.executable, "--launch-tool", "ui_cropper"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation,  # Hide console
                text=True
            )

            # Wait a bit to see if there are immediate errors
            try:
                stdout, stderr = proc.communicate(timeout=2)
                if proc.returncode != 0:
                    if device_log:
                        device_log(f"[ERROR] Tool launch failed with return code {proc.returncode}")
                        if stdout:
                            device_log(f"[ERROR] stdout: {stdout}")
                        if stderr:
                            device_log(f"[ERROR] stderr: {stderr}")
                    toast(f"Tool launch failed: {stderr or stdout or 'Unknown error'}")
                    return False
            except subprocess.TimeoutExpired:
                # Tool is still running, which is good
                if device_log:
                    device_log("[INFO] Tool started successfully (packaged mode)")
                return True

            return True

        # Development mode: try script path first
        if not is_frozen and script_path and os.path.isfile(script_path):
            subprocess.Popen(
                [python, script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation
            )
            if device_log:
                device_log(f"[INFO] Tool started (script): {script_path}")
            return True

        # When no script file, try to start as module (adapt to certain packaging layouts)
        if _can_run_module():
            subprocess.Popen(
                [python, "-m", "mumu_adb_controller.tools.ui_cropper_updated_v2"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation
            )
            if device_log:
                device_log("[INFO] Tool started (module): mumu_adb_controller.tools.ui_cropper_updated_v2")
            return True

        # All methods failed
        toast("Tool not found: tools/ui_cropper_updated_v2.py (please confirm tools/ exists in project root, or module is importable)")
        return False

    except Exception as e:
        if device_log:
            device_log(f"[ERROR] Exception in launch_ui_cropper: {e}")
        toast(f"Launch failed: {e}")
        return False
