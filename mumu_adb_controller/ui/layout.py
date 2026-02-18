import tkinter as tk

def restore_paned_width(app, paned: tk.PanedWindow, index: int, target: int, retries: int = 6, delay_ms: int = 100):
    def try_set(i=0):
        try:
            app.update_idletasks()
            paned.sashpos(index, target)
        except Exception:
            pass
        ok = False
        try:
            ok = (paned.sashpos(index) == target)
        except Exception:
            ok = False
        if not ok and i < retries:
            app.after(delay_ms, lambda: try_set(i+1))
    app.after_idle(try_set)

def save_paned_width(app, paned: tk.PanedWindow, index: int, default_: int) -> int:
    try:
        app.update_idletasks()
        return int(paned.sashpos(index))
    except Exception:
        return default_
