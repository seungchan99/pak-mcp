# -*- coding: utf-8 -*-
"""Reset the PAK Graphic Definition by sending Ctrl+N (New) to its window.
Requires: pip install uiautomation. Run with PAK open."""
import sys, time
try:
    import uiautomation as auto
except Exception:
    print("ERROR: pip install uiautomation"); sys.exit(1)

def find_window(substr):
    for w in auto.GetRootControl().GetChildren():
        try:
            if substr.lower() in (w.Name or "").lower():
                return w
        except Exception:
            pass
    return None

win = find_window("Graphic Definition")
if not win:
    print("Graphic Definition window not found. Open it first (pak_open_graphdef)."); sys.exit(1)
win.SetActive(); time.sleep(0.3)
win.SendKeys('{Ctrl}n')
print("Sent Ctrl+N to '%s' (New / reset)." % win.Name)
