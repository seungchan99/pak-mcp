# -*- coding: utf-8 -*-
"""Screenshot the PAK Graphic Viewer to C:/MCPProject_pak/order_shot.png
(no reconfiguration -- just captures whatever is currently displayed).

    python pak_shot.py
"""
from __future__ import annotations
import time
OUT = "C:/MCPProject_pak/order_shot.png"

try:
    import uiautomation as auto
    from PIL import ImageGrab
except Exception as e:
    print("need uiautomation + pillow:", e); raise SystemExit

win = None
for w in auto.GetRootControl().GetChildren():
    try:
        if w.ControlTypeName == "WindowControl" and "graphic viewer" in (w.Name or "").lower():
            win = w; break
    except Exception:
        pass
if not win:
    print("Graphic Viewer window not found"); raise SystemExit
try: win.SetActive()
except Exception: pass
time.sleep(0.5)
r = win.BoundingRectangle
bbox = (r.left, r.top, r.right, r.bottom)
img = ImageGrab.grab(bbox=bbox, all_screens=True)
img.save(OUT)
print("saved:", OUT, "size", img.size)
