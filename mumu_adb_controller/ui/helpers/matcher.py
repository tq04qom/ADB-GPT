
import os

try:
    import cv2
    import numpy as np
    _HAS_CV = True
except Exception:
    _HAS_CV = False

THRESH = 0.85
SCALES = [1.0]

def has_cv():
    return _HAS_CV

def match_one(screen_png: bytes, tpl_path: str, threshold: float = THRESH):
    """
    返回 (found: bool, (x,y)): 模板中心坐标，基于 TM_CCOEFF_NORMED。
    要求：screen_png 是 PNG 字节；tpl_path 为模板文件路径。
    """
    if not _HAS_CV or not screen_png or not os.path.isfile(tpl_path):
        return (False, (0, 0))

    try:
        screen_arr = np.frombuffer(screen_png, dtype=np.uint8)
        scr = cv2.imdecode(screen_arr, cv2.IMREAD_COLOR)
        if scr is None:
            return (False, (0, 0))
        gray = cv2.cvtColor(scr, cv2.COLOR_BGR2GRAY)

        tpl = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            return (False, (0, 0))

        h, w = tpl.shape[:2]
        best = (0.0, None, None, None)  # (score, top_left, tw, th)
        for s in SCALES:
            tw = max(10, int(w * s))
            th = max(10, int(h * s))
            if tw >= gray.shape[1] or th >= gray.shape[0]:
                continue
            tpl_s = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(gray, tpl_s, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best[0]:
                best = (max_val, max_loc, tw, th)

        score, tl, bw, bh = best
        if score >= threshold and tl is not None:
            x = tl[0] + bw // 2
            y = tl[1] + bh // 2
            return (True, (int(x), int(y)))
        return (False, (0, 0))
    except Exception:
        return (False, (0, 0))

def exist(screen_png: bytes, tpl_path: str, threshold: float = THRESH):
    found, _ = match_one(screen_png, tpl_path, threshold=threshold)
    return found

def exist_all(screen_png: bytes, paths: dict, keys: list, threshold: float = THRESH):
    for k in keys:
        ok, _ = match_one(screen_png, paths[k], threshold=threshold)
        if not ok:
            return False
    return True



def match_one_detail(screen_png: bytes, tpl_path: str, threshold: float = THRESH):
    """
    返回 (found: bool, (x,y), score: float)。
    与 match_one 一致，但额外返回匹配得分，便于详细日志。
    """
    if not _HAS_CV or not screen_png or not os.path.isfile(tpl_path):
        return (False, (0, 0), 0.0)
    try:
        screen_arr = np.frombuffer(screen_png, dtype=np.uint8)
        scr = cv2.imdecode(screen_arr, cv2.IMREAD_COLOR)
        if scr is None:
            return (False, (0, 0), 0.0)
        gray = cv2.cvtColor(scr, cv2.COLOR_BGR2GRAY)
        tpl = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            return (False, (0, 0), 0.0)
        h, w = tpl.shape[:2]
        best = (0.0, None, None, None)  # (score, top_left, tw, th)
        for s in SCALES:
            tw = max(10, int(w * s))
            th = max(10, int(h * s))
            if tw >= gray.shape[1] or th >= gray.shape[0]:
                continue
            tpl_s = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(gray, tpl_s, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best[0]:
                best = (max_val, max_loc, tw, th)
        score, tl, bw, bh = best
        if tl is not None:
            x = tl[0] + bw // 2
            y = tl[1] + bh // 2
            ok = score >= threshold
            return (ok, (int(x), int(y)), float(score))
        return (False, (0, 0), float(score))
    except Exception:
        return (False, (0, 0), 0.0)

def match_in_range(screen_png: bytes, tpl_path: str, coord_range: tuple, threshold: float = THRESH):
    """
    在指定范围内匹配模板。

    参数:
        screen_png: 屏幕截图（PNG字节）
        tpl_path: 模板文件路径
        coord_range: 搜索范围 ((x1, y1), (x2, y2))
        threshold: 匹配阈值

    返回:
        (found: bool, (x, y)): 模板中心坐标（基于原始屏幕坐标系）
    """
    if not _HAS_CV or not screen_png or not os.path.isfile(tpl_path):
        return (False, (0, 0))

    try:
        screen_arr = np.frombuffer(screen_png, dtype=np.uint8)
        scr = cv2.imdecode(screen_arr, cv2.IMREAD_COLOR)
        if scr is None:
            return (False, (0, 0))

        # 提取指定范围
        (x1, y1), (x2, y2) = coord_range
        roi = scr[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        tpl = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            return (False, (0, 0))

        h, w = tpl.shape[:2]
        best = (0.0, None, None, None)  # (score, top_left, tw, th)
        for s in SCALES:
            tw = max(10, int(w * s))
            th = max(10, int(h * s))
            if tw >= gray.shape[1] or th >= gray.shape[0]:
                continue
            tpl_s = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(gray, tpl_s, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best[0]:
                best = (max_val, max_loc, tw, th)

        score, tl, bw, bh = best
        if score >= threshold and tl is not None:
            # 转换回原始坐标系
            x = tl[0] + bw // 2 + x1
            y = tl[1] + bh // 2 + y1
            return (True, (int(x), int(y)))
        return (False, (0, 0))
    except Exception:
        return (False, (0, 0))
